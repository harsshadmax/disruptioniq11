import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.audit.service import verify_chain, write_audit


def _write(db, n=1, action="test.event"):
    rows = [
        write_audit(db, actor_id=None, role=None, action=action, entity_type="test", entity_id=i, payload={"i": i})
        for i in range(n)
    ]
    db.commit()
    return rows


def test_chain_links_and_verifies(db):
    first, second = _write(db, 2)
    assert second.prev_hash == first.row_hash
    ok, bad, count = verify_chain(db)
    assert ok and bad is None and count >= 2


def test_update_is_blocked_by_trigger(db):
    row = _write(db)[0]
    with pytest.raises(DBAPIError, match="append-only"):
        db.execute(text("UPDATE audit_log SET reason = 'edited' WHERE id = :i"), {"i": row.id})
    db.rollback()


def test_delete_is_blocked_by_trigger(db):
    row = _write(db)[0]
    with pytest.raises(DBAPIError, match="append-only"):
        db.execute(text("DELETE FROM audit_log WHERE id = :i"), {"i": row.id})
    db.rollback()


def test_truncate_is_blocked_by_trigger(db):
    _write(db)
    with pytest.raises(DBAPIError, match="append-only"):
        db.execute(text("TRUNCATE audit_log"))
    db.rollback()


def test_tampering_is_detected_by_hash_chain(db):
    rows = _write(db, 3)
    # Simulate an attacker with DB owner rights who disables the trigger and edits a row.
    db.execute(text("ALTER TABLE audit_log DISABLE TRIGGER audit_log_no_update_delete"))
    db.execute(text("UPDATE audit_log SET reason = 'forged' WHERE id = :i"), {"i": rows[1].id})
    ok, bad, _ = verify_chain(db)
    assert not ok and bad == rows[1].id
    db.rollback()  # DDL is transactional in Postgres: the trigger comes back
