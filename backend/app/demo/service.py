"""Demo controls (Administrator only): fire each guard on purpose and report what it did.

Nothing here bypasses a rule. Each action calls the same service function a real request would (the webhook
processor, plan approval), so the guard under test does the refusing and writes its own audit row. On top of that
each run writes one `demo.*` row by the administrator listing every step, so the audit page tells the whole story.
"""
from datetime import datetime, timedelta, timezone

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.act import service
from app.act.errors import Conflict, WorkflowError
from app.act.rules import approval_block
from app.audit.service import write_audit
from app.auth.permissions import can
from app.enums import EventOutcome, PlanStatus
from app.ingest.webhook import CarrierEvent, idem_key, process_event
from app.models import Plan, Shipment, ShipmentEvent, User


class DemoStep(BaseModel):
    label: str
    status_code: int
    outcome: str
    detail: str | None = None


class DemoResult(BaseModel):
    action: str
    headline: str
    guard_held: bool  # True when the system refused / ignored the bad input, as it should
    steps: list[DemoStep]


class DemoTargets(BaseModel):
    last_event: str | None  # e.g. "SHP-1042 seq 1 (delayed)"
    proposed_plan_id: int | None
    proposed_plan: str | None


def _last_applied(db: Session) -> ShipmentEvent | None:
    return db.execute(select(ShipmentEvent).where(ShipmentEvent.outcome == EventOutcome.APPLIED)
                      .order_by(ShipmentEvent.id.desc()).limit(1)).scalar_one_or_none()


def _proposed_plan(db: Session) -> Plan | None:
    return db.execute(select(Plan).where(Plan.status == PlanStatus.PROPOSED)
                      .order_by(Plan.updated_at.desc(), Plan.id.desc()).limit(1)).scalar_one_or_none()


def _plan_label(plan: Plan) -> str:
    return f"plan #{plan.id} ({plan.type.replace('_', ' ')})"


def targets(db: Session) -> DemoTargets:
    ev, plan = _last_applied(db), _proposed_plan(db)
    return DemoTargets(
        last_event=f"{ev.payload_json.get('shipment_ref')} seq {ev.seq} ({ev.event_type})" if ev else None,
        proposed_plan_id=plan.id if plan else None,
        proposed_plan=_plan_label(plan) if plan else None,
    )


def _record(db: Session, admin: User, result: DemoResult, entity_id: str | int | None) -> DemoResult:
    write_audit(db, actor_id=admin.id, role=admin.role, action=f"demo.{result.action}", entity_type="demo",
                entity_id=entity_id, reason=result.headline,
                payload={"guard_held": result.guard_held, "steps": [s.model_dump() for s in result.steps]})
    return result


def replay_duplicate(db: Session, admin: User) -> DemoResult:
    """Send the last applied carrier event again: the idempotency key must make it a no-op."""
    ev = _last_applied(db)
    if ev is None:
        raise Conflict("No carrier event has been applied yet. Fire a scenario first (python -m app.scenarios s1).")
    event = CarrierEvent.model_validate(ev.payload_json)
    out = process_event(db, event)
    held = out.outcome == EventOutcome.DUPLICATE
    result = DemoResult(
        action="replay_duplicate", guard_held=held,
        headline=("Duplicate ignored: nothing changed." if held else f"Unexpected outcome: {out.outcome}"),
        steps=[DemoStep(label=f"Resend {event.shipment_ref} {event.event_type} (seq {event.seq})",
                        status_code=out.status_code, outcome=out.outcome, detail=out.detail)])
    return _record(db, admin, result, event.shipment_ref)


def stale_event(db: Session, admin: User) -> DemoResult:
    """Send an out-of-order event (a sequence number the shipment has already passed): it must be refused."""
    ev = _last_applied(db)
    ship = db.get(Shipment, ev.shipment_id) if ev else None
    if ship is None or ship.last_seq < 1:
        raise Conflict("No shipment has applied events yet. Fire a scenario first (python -m app.scenarios s1).")
    now = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    event = None
    for back in range(1, 120):  # a time bucket no earlier demo click used, so it is judged on its sequence number
        candidate = CarrierEvent(carrier=ship.carrier, shipment_ref=ship.ref, event_type="in_transit",
                                 seq=ship.last_seq, occurred_at=now - timedelta(hours=3, minutes=back))
        taken = db.execute(select(ShipmentEvent.id).where(ShipmentEvent.idem_key == idem_key(candidate))).first()
        if not taken:
            event = candidate
            break
    if event is None:
        raise Conflict("Too many stale demo events already; nothing more to show.")
    seq_before = ship.last_seq
    out = process_event(db, event)
    db.refresh(ship)
    held = out.outcome == EventOutcome.STALE and ship.last_seq == seq_before
    result = DemoResult(
        action="stale_event", guard_held=held,
        headline=("Stale event rejected: the shipment kept its newer state." if held else f"Unexpected outcome: {out.outcome}"),
        steps=[DemoStep(label=f"Send {ship.ref} in_transit with seq {event.seq} (already at {seq_before})",
                        status_code=out.status_code, outcome=out.outcome, detail=out.detail)])
    return _record(db, admin, result, ship.ref)


def _attempt(label: str, fn) -> tuple[DemoStep, bool]:
    """Run one workflow call; returns the step and whether it went through."""
    try:
        plan = fn()
    except WorkflowError as exc:
        return DemoStep(label=label, status_code=exc.status_code, outcome="refused", detail=exc.detail), False
    return DemoStep(label=label, status_code=200, outcome="done", detail=f"plan is now {plan.status}"), True


def self_approval(db: Session, admin: User) -> DemoResult:
    """Make someone who proposed or modified the plan try to approve it. The workflow must refuse and audit it."""
    plan = _proposed_plan(db)
    if plan is None:
        raise Conflict("No plan is awaiting approval. Propose one first (as the Operations Analyst).")
    perm = f"plan.approve:{plan.type}"
    modifiers = [u for u in (db.get(User, i) for i in plan.modified_by_ids or []) if u and can(u.role, perm)]
    actor = modifiers[0] if modifiers else (db.get(User, plan.proposer_id) if plan.proposer_id else None)
    if actor is None:
        raise Conflict("This plan has no recorded proposer.")
    if can(actor.role, perm) and approval_block(actor.id, plan.proposer_id, plan.modified_by_ids) is None:
        raise Conflict(f"{actor.name} would be allowed to approve {_plan_label(plan)}, so nothing was attempted.")
    step, went_through = _attempt(f"{actor.name} ({actor.role.replace('_', ' ')}) tries to approve {_plan_label(plan)}",
                                  lambda: service.approve(db, actor, plan.id, plan.version))
    result = DemoResult(
        action="self_approval", guard_held=not went_through,
        headline="Blocked and audited." if not went_through else "The approval went through (it should not have).",
        steps=[step])
    return _record(db, admin, result, plan.id)


def double_approve(db: Session, admin: User) -> DemoResult:
    """Approve the same plan twice with the same version, as two browser tabs would. The second must get a 409.

    The first approval is real: the plan moves to APPROVED, exactly as if the eligible approver had clicked.
    """
    plan = _proposed_plan(db)
    if plan is None:
        raise Conflict("No plan is awaiting approval. Propose one first (as the Operations Analyst).")
    perm = f"plan.approve:{plan.type}"
    eligible = db.execute(select(User).where(User.is_active.is_(True)).order_by(User.id)).scalars()
    approver = next((u for u in eligible if can(u.role, perm)
                     and approval_block(u.id, plan.proposer_id, plan.modified_by_ids) is None), None)
    if approver is None:
        raise Conflict(f"Nobody is eligible to approve {_plan_label(plan)}: the approver may not have proposed or modified it.")
    version, plan_id = plan.version, plan.id
    who = f"{approver.name} ({approver.role.replace('_', ' ')})"
    first, ok = _attempt(f"Tab 1: {who} approves {_plan_label(plan)} (version {version})",
                         lambda: service.approve(db, approver, plan_id, version))
    db.commit()  # tab 1 finished before tab 2 sends its request
    second, ok2 = _attempt(f"Tab 2: the same approval again, still holding version {version}",
                           lambda: service.approve(db, approver, plan_id, version))
    held = ok and not ok2 and second.status_code == 409
    result = DemoResult(
        action="double_approve", guard_held=held,
        headline="Second approval refused with 409: only one approval counts." if held else "Unexpected result; see the steps.",
        steps=[first, second])
    return _record(db, admin, result, plan_id)
