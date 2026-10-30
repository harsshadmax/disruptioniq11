"""Append-only audit writer with a tamper-evident hash chain."""
import hashlib
import json
from datetime import datetime, timezone

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.models import AuditLog

GENESIS_HASH = "0" * 64
_CHAIN_LOCK_KEY = 7001  # serialises writers so the chain has one linear order


def _canonical(payload: dict | None) -> str:
    return json.dumps(payload or {}, sort_keys=True, separators=(",", ":"), default=str)


def compute_hash(
    prev_hash: str,
    ts: datetime,
    actor_id: int | None,
    role: str | None,
    action: str,
    entity_type: str,
    entity_id: str | None,
    reason: str | None,
    payload: dict | None,
) -> str:
    parts = [
        prev_hash,
        ts.astimezone(timezone.utc).isoformat(timespec="microseconds"),
        "" if actor_id is None else str(actor_id),
        role or "",
        action,
        entity_type,
        entity_id or "",
        reason or "",
        _canonical(payload),
    ]
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


def write_audit(
    db: Session,
    *,
    actor_id: int | None,
    role: str | None,
    action: str,
    entity_type: str,
    entity_id: str | int | None = None,
    reason: str | None = None,
    payload: dict | None = None,
) -> AuditLog:
    db.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": _CHAIN_LOCK_KEY})
    prev = db.execute(select(AuditLog.row_hash).order_by(AuditLog.id.desc()).limit(1)).scalar_one_or_none()
    prev = prev or GENESIS_HASH
    ts = datetime.now(timezone.utc)
    eid = None if entity_id is None else str(entity_id)
    entry = AuditLog(
        ts=ts,
        actor_id=actor_id,
        role=role,
        action=action,
        entity_type=entity_type,
        entity_id=eid,
        reason=reason,
        payload_json=payload or {},
        prev_hash=prev,
        row_hash=compute_hash(prev, ts, actor_id, role, action, entity_type, eid, reason, payload),
    )
    db.add(entry)
    db.flush()
    return entry


def verify_chain(db: Session) -> tuple[bool, int | None, int]:
    """Return (ok, first_bad_id, rows_checked)."""
    prev = GENESIS_HASH
    count = 0
    # populate_existing: always compare what is in the database, not rows cached in this session
    stmt = select(AuditLog).order_by(AuditLog.id).execution_options(populate_existing=True)
    for row in db.execute(stmt).scalars():
        count += 1
        expected = compute_hash(
            row.prev_hash, row.ts, row.actor_id, row.role, row.action,
            row.entity_type, row.entity_id, row.reason, row.payload_json,
        )
        if row.prev_hash != prev or row.row_hash != expected:
            return False, row.id, count
        prev = row.row_hash
    return True, None, count
