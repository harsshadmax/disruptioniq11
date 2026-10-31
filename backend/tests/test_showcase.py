"""The showcase seeder leaves every city, plan status and disruption type on screen, through the real services."""
from datetime import date

import pytest
from sqlalchemy import func, select

from app.audit.service import verify_chain
from app.models import AuditLog, Disruption, ImportBatch, ImportRowError, Notification, Plan, ShipmentEvent, Warehouse
from app.synth import showcase
from app.synth.generator import generate
from app.synth.loader import load_synth


@pytest.fixture
def seeded(db, users):
    load_synth(db, generate(42, date.today()), seed=42)
    showcase.seed(db)
    return db


def test_every_city_has_a_disruption_and_every_type_and_severity_appears(seeded):
    rows = seeded.execute(select(Warehouse.name, Disruption.type, Disruption.severity, Disruption.status)
                          .join(Warehouse, Warehouse.id == Disruption.warehouse_id)).all()
    assert {r[0] for r in rows} == {"Chennai", "Bengaluru", "Mumbai", "Delhi"}
    assert {r[1] for r in rows} == {"late_shipment", "supplier_delay", "stock_shortage"}
    assert {r[2] for r in rows} == {"high", "medium", "low"}
    assert {r[3] for r in rows} == {"active", "resolved"}
    for city in ("Chennai", "Bengaluru", "Mumbai", "Delhi"):
        assert any(r[0] == city and r[3] == "active" for r in rows), f"{city} has nothing active"


def test_plans_reach_every_status_a_person_can_see(seeded):
    statuses = set(seeded.execute(select(Plan.status)).scalars())
    assert statuses == {"DRAFT", "PROPOSED", "APPROVED", "COMPLETED", "REJECTED", "STALE", "CANCELLED"}


def test_a_reallocate_plan_waits_for_each_person_who_must_act(seeded):
    waiting = seeded.execute(select(Plan.type, Plan.status).where(Plan.status.in_(["PROPOSED", "APPROVED"]))).all()
    assert ("reallocate", "PROPOSED") in waiting  # the manager's queue
    assert ("reallocate", "APPROVED") in waiting  # the Chennai operator's queue
    assert ("expedite", "PROPOSED") in waiting and ("expedite", "APPROVED") in waiting  # procurement and the analyst


def test_refusals_imports_and_events_leave_a_trace(seeded):
    actions = set(seeded.execute(select(AuditLog.action)).scalars())
    assert {"access_denied", "approval_blocked", "plan.reject", "plan.stale", "disruption.resolved",
            "webhook.duplicate", "webhook.stale", "webhook.invalid"} <= actions
    assert {"applied", "invalid", "stale"} <= set(seeded.execute(select(ShipmentEvent.outcome)).scalars())
    assert seeded.execute(select(func.count(ImportRowError.id))).scalar_one() >= 4
    assert seeded.execute(select(func.count(ImportBatch.id)).where(ImportBatch.entity == "inventory")).scalar_one() >= 2
    assert verify_chain(seeded)[0]


def test_the_inbox_has_read_and_unread_items(seeded):
    read = seeded.execute(select(func.count(Notification.id)).where(Notification.read_at.is_not(None))).scalar_one()
    unread = seeded.execute(select(func.count(Notification.id)).where(Notification.read_at.is_(None))).scalar_one()
    assert read > 0 and unread > 0


def test_the_scripted_scenarios_still_have_their_shipments_untouched(seeded):
    from app.models import Shipment
    for ref in ("SHP-1042", "SHP-1077"):
        ship = seeded.execute(select(Shipment).where(Shipment.ref == ref)).scalar_one()
        assert ship.last_seq == 0, f"{ref} would no longer accept the demo scenario's first event"
