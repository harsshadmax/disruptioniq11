from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit.service import verify_chain
from app.auth.deps import require
from app.db import get_db
from app.models import AuditLog, User

router = APIRouter(prefix="/audit", tags=["audit"])


@router.get("")
def list_audit(
    action: str | None = None,
    entity_type: str | None = None,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    _: User = Depends(require("audit.read")),
    db: Session = Depends(get_db),
) -> list[dict]:
    q = select(AuditLog).order_by(AuditLog.id.desc()).limit(limit).offset(offset)
    if action:
        q = q.where(AuditLog.action == action)
    if entity_type:
        q = q.where(AuditLog.entity_type == entity_type)
    return [
        {
            "id": r.id, "ts": r.ts, "actor_id": r.actor_id, "role": r.role, "action": r.action,
            "entity_type": r.entity_type, "entity_id": r.entity_id, "reason": r.reason,
            "payload": r.payload_json, "row_hash": r.row_hash,
        }
        for r in db.execute(q).scalars()
    ]


@router.get("/verify")
def verify(_: User = Depends(require("audit.read")), db: Session = Depends(get_db)) -> dict:
    ok, bad_id, count = verify_chain(db)
    return {"ok": ok, "first_bad_id": bad_id, "rows_checked": count}
