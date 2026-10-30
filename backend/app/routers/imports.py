import csv
import io
from typing import Any, Literal

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit.service import write_audit
from app.auth.deps import require
from app.db import get_db
from app.detect.service import refresh_disruptions
from app.ingest.importers import SPECS, run_import
from app.models import ImportBatch, ImportRowError, User

router = APIRouter(prefix="/import", tags=["import"])

Entity = Literal["orders", "inventory", "shipments"]
MAX_ROWS = 5000
MAX_BYTES = 2 * 1024 * 1024


class ErrorOut(BaseModel):
    row_no: int
    field: str | None
    reason: str


class ImportResult(BaseModel):
    batch_id: int
    source: str
    entity: str
    filename: str | None
    rows_total: int
    rows_ok: int
    rows_failed: int
    errors: list[ErrorOut]


class JsonImport(BaseModel):
    entity: Entity
    rows: list[Any] = Field(max_length=MAX_ROWS)


def _result(batch: ImportBatch, errors: list[ImportRowError]) -> ImportResult:
    return ImportResult(
        batch_id=batch.id, source=batch.source, entity=batch.entity, filename=batch.filename,
        rows_total=batch.rows_ok + batch.rows_failed, rows_ok=batch.rows_ok, rows_failed=batch.rows_failed,
        errors=[ErrorOut(row_no=e.row_no, field=e.field, reason=e.reason) for e in errors],
    )


def _finish(db: Session, user: User, batch: ImportBatch, errors: list[ImportRowError]) -> ImportResult:
    write_audit(db, actor_id=user.id, role=user.role, action="import.run", entity_type="import_batch",
                entity_id=batch.id, payload={"entity": batch.entity, "source": batch.source, "filename": batch.filename,
                                             "rows_ok": batch.rows_ok, "rows_failed": batch.rows_failed})
    if batch.rows_ok:
        refresh_disruptions(db)
    db.commit()
    return _result(batch, errors)


def _read_csv(data: bytes, entity: str) -> list[tuple[int, dict]]:
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "File must be UTF-8 encoded CSV")
    reader = csv.DictReader(io.StringIO(text))
    headers = [h.strip().lower() for h in (reader.fieldnames or []) if h is not None]
    missing = [c for c in SPECS[entity].columns if c not in headers]
    if missing:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"Missing required column(s): {', '.join(missing)}")
    reader.fieldnames = [(h or "").strip().lower() for h in reader.fieldnames]
    rows: list[tuple[int, dict]] = []
    for line_no, raw in enumerate(reader, start=2):  # line 1 is the header
        if len(rows) >= MAX_ROWS:
            raise HTTPException(413, f"At most {MAX_ROWS} rows per file")
        if None in raw:  # more cells than headers
            rows.append((line_no, "too many columns"))  # not a dict: reported as a bad row
            continue
        rows.append((line_no, {k: (v.strip() if isinstance(v, str) and v.strip() != "" else None) for k, v in raw.items()}))
    return rows


@router.post("/csv", response_model=ImportResult)
def import_csv(
    entity: Entity = Query(...),
    file: UploadFile = File(...),
    user: User = Depends(require("import.run")),
    db: Session = Depends(get_db),
) -> ImportResult:
    data = file.file.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise HTTPException(413, "File larger than 2 MB")
    batch, errors = run_import(db, entity=entity, rows=_read_csv(data, entity), source="csv",
                               filename=(file.filename or "")[:200] or None, user_id=user.id)
    return _finish(db, user, batch, errors)


@router.post("/json", response_model=ImportResult)
def import_json(body: JsonImport, user: User = Depends(require("import.run")), db: Session = Depends(get_db)) -> ImportResult:
    rows = [(i, r) for i, r in enumerate(body.rows, start=1)]
    batch, errors = run_import(db, entity=body.entity, rows=rows, source="json", filename=None, user_id=user.id)
    return _finish(db, user, batch, errors)


@router.get("/batches", response_model=list[ImportResult])
def list_batches(limit: int = Query(20, ge=1, le=100), _: User = Depends(require("view")),
                 db: Session = Depends(get_db)) -> list[ImportResult]:
    batches = db.execute(select(ImportBatch).order_by(ImportBatch.id.desc()).limit(limit)).scalars().all()
    return [_result(b, []) for b in batches]


@router.get("/batches/{batch_id}", response_model=ImportResult)
def get_batch(batch_id: int, _: User = Depends(require("view")), db: Session = Depends(get_db)) -> ImportResult:
    batch = db.get(ImportBatch, batch_id)
    if batch is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Import batch not found")
    errors = db.execute(select(ImportRowError).where(ImportRowError.batch_id == batch_id)
                        .order_by(ImportRowError.row_no, ImportRowError.id)).scalars().all()
    return _result(batch, list(errors))
