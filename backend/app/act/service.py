"""Plan workflow: propose, modify, approve, reject, confirm execution (blueprint sections 4, 5, 7.6).

Every rule is enforced here, in the service layer, not in the UI or the route. Every blocked attempt writes an
audit row before the error is raised; the router commits that row. Concurrency: the plan row is locked FOR UPDATE,
the caller sends the version it saw (409 if stale), and the ORM version column is a second line of defence.
"""
from datetime import datetime, timezone

from sqlalchemy import delete, select
from sqlalchemy.orm import Session
from sqlalchemy.orm.exc import StaleDataError

from app.act.errors import Conflict, Forbidden, Invalid, NotFound
from app.act.execution import ExecutionFailed, apply_effects, check_preconditions
from app.act.rules import ACTIVE, approval_block, can_transition, execution_block
from app.audit.service import write_audit
from app.auth.permissions import can
from app.detect.service import run_detection
from app.enums import PlanStatus as S
from app.enums import Role
from app.models import Disruption, Plan, PlanStep, Sku, User, Warehouse
from app.notify.service import notify, recipients
from app.options.generators import MODIFIABLE, overrides_from_params, recompute_option
from app.options.service import build_context


def _lock(db: Session, user: User, plan_id: int) -> tuple[Plan, Disruption]:
    plan = db.execute(select(Plan).where(Plan.id == plan_id).with_for_update()
                      .execution_options(populate_existing=True)).scalar_one_or_none()
    d = db.get(Disruption, plan.disruption_id) if plan else None
    # an operator never learns that another warehouse's plan exists
    if plan is None or (user.role == Role.OPERATOR and (user.warehouse_id is None or user.warehouse_id != d.warehouse_id)):
        raise NotFound("Plan not found")
    return plan, d


def _audit(db: Session, user: User, action: str, plan: Plan, reason: str | None = None, payload: dict | None = None):
    write_audit(db, actor_id=user.id, role=user.role, action=action, entity_type="plan", entity_id=plan.id,
                reason=reason, payload={"type": plan.type, "disruption_id": plan.disruption_id} | (payload or {}))


def _authorize(db: Session, user: User, permission: str, plan: Plan) -> None:
    if not can(user.role, permission):
        write_audit(db, actor_id=user.id, role=user.role, action="access_denied", entity_type="permission",
                    entity_id=permission, reason=f"role lacks permission (plan {plan.id})")
        raise Forbidden("Your role is not allowed to do this")


def _check_version(plan: Plan, expected: int) -> None:
    if plan.version != expected:
        raise Conflict(f"This plan changed since you loaded it (now version {plan.version}). Reload and try again.")


def _move(plan: Plan, dst: str) -> None:
    if not can_transition(plan.status, dst):
        raise Conflict(f"Plan is {plan.status}; it cannot move to {dst}")
    plan.status = dst


def _label(plan: Plan, d: Disruption, db: Session) -> str:
    return f"Plan #{plan.id} ({plan.type.replace('_', ' ')}) for {db.get(Sku, d.sku_id).code} at {db.get(Warehouse, d.warehouse_id).name}"


def _money(m: dict) -> str:
    return f"saves {m.get('orders_saved', 0)} order(s) for a cost of {m.get('cost', 0):,.0f}"


def propose(db: Session, user: User, plan_id: int, expected_version: int) -> Plan:
    plan, d = _lock(db, user, plan_id)
    _check_version(plan, expected_version)
    if plan.status != S.DRAFT:
        raise Conflict(f"Plan is {plan.status}; only a DRAFT can be proposed")
    if not plan.metrics_json.get("feasible"):
        raise Invalid("An infeasible option cannot be proposed: " + "; ".join(plan.metrics_json.get("reasons", [])))
    if d.status != "active":
        raise Conflict("The disruption is resolved")
    # serialise proposals for one disruption: the plan row lock alone lets two different plans both pass the check below
    db.execute(select(Disruption.id).where(Disruption.id == d.id).with_for_update())
    busy = db.execute(select(Plan.id).where(Plan.disruption_id == d.id, Plan.status.in_(ACTIVE))).first()
    if busy:
        raise Conflict(f"Plan #{busy[0]} is already in progress for this disruption")
    _move(plan, S.PROPOSED)
    plan.proposer_id = user.id
    db.flush()
    _audit(db, user, "plan.propose", plan, payload={"metrics": _brief(plan)})
    notify(db, recipients(db, f"plan.approve:{plan.type}"), "plan.proposed",
           f"{_label(plan, d, db)} awaits your approval: {_money(plan.metrics_json)}.", f"plan:{plan.id}", exclude_id=user.id)
    return plan


def _brief(plan: Plan) -> dict:
    m = plan.metrics_json
    return {k: m.get(k) for k in ("orders_saved", "cost", "penalty_avoided", "net_benefit")}


def _validate_changes(plan_type: str, changes: dict) -> dict:
    allowed = MODIFIABLE[plan_type]
    if not changes:
        raise Invalid("No changes given")
    bad = sorted(set(changes) - allowed)
    if bad:
        raise Invalid(f"Cannot change {', '.join(bad)} on a {plan_type} plan; you can change: {', '.join(sorted(allowed))}")
    out = {}
    for k, v in changes.items():
        if k == "order_refs":
            if not isinstance(v, list) or not v or not all(isinstance(x, str) for x in v):
                raise Invalid("order_refs must be a non-empty list of order references")
            out[k] = v
        else:
            if isinstance(v, bool) or not isinstance(v, int) or v < 1:
                raise Invalid(f"{k} must be a whole number of at least 1")
            out[k] = v
    return out


def modify(db: Session, user: User, plan_id: int, expected_version: int, changes: dict,
           now: datetime | None = None) -> Plan:
    now = now or datetime.now(timezone.utc)
    plan, d = _lock(db, user, plan_id)
    allowed_roles = {S.DRAFT: {Role.ANALYST, Role.MANAGER}, S.PROPOSED: {Role.MANAGER, Role.PROCUREMENT}}
    if plan.status not in allowed_roles:
        raise Conflict(f"Plan is {plan.status}; only a DRAFT or PROPOSED plan can be modified")
    if user.role not in allowed_roles[plan.status]:
        _audit(db, user, "modify_blocked", plan, reason=f"role {user.role} may not modify a {plan.status} plan")
        raise Forbidden(f"Your role may not modify a {plan.status} plan")
    _check_version(plan, expected_version)
    changes = _validate_changes(plan.type, changes)
    ctx = build_context(db, d, now.date())
    result = recompute_option(ctx, plan.type, **(overrides_from_params(plan.type, plan.params_json) | changes)) if ctx else None
    if result is None or not result.feasible:
        reasons = result.reasons if result else ["the disruption has no data"]
        _audit(db, user, "plan.modify_rejected", plan, reason="; ".join(reasons), payload={"changes": changes})
        raise Invalid("The modified plan is not feasible: " + "; ".join(reasons))
    before = _brief(plan)
    old = plan.metrics_json
    plan.params_json = result.params
    plan.metrics_json = result.metrics | {"feasible": True, "reasons": result.reasons, "rank": old.get("rank"),
                                          "recommended": old.get("recommended", False)}
    if user.id not in (plan.modified_by_ids or []):
        plan.modified_by_ids = [*(plan.modified_by_ids or []), user.id]
    db.execute(delete(PlanStep).where(PlanStep.plan_id == plan.id))
    db.add_all([PlanStep(plan_id=plan.id, seq=i, description=t[:240]) for i, t in enumerate(result.steps, 1)])
    db.flush()
    _audit(db, user, "plan.modify", plan, payload={"changes": changes, "before": before, "after": _brief(plan)})
    if plan.status == S.PROPOSED:
        notify(db, [plan.proposer_id, *recipients(db, f"plan.approve:{plan.type}")], "plan.modified",
               f"{_label(plan, d, db)} was modified by {user.name}: now {_money(plan.metrics_json)}.", f"plan:{plan.id}",
               exclude_id=user.id)
    return plan


def approve(db: Session, user: User, plan_id: int, expected_version: int) -> Plan:
    plan, d = _lock(db, user, plan_id)
    _authorize(db, user, f"plan.approve:{plan.type}", plan)
    _check_version(plan, expected_version)
    if plan.status != S.PROPOSED:
        raise Conflict(f"Plan is {plan.status}, not awaiting approval")
    reason = approval_block(user.id, plan.proposer_id, plan.modified_by_ids)
    if reason:
        _audit(db, user, "approval_blocked", plan, reason=reason)
        raise Forbidden(f"You cannot approve this plan: {reason}")
    _move(plan, S.APPROVED)
    plan.approver_id = user.id
    db.flush()
    _audit(db, user, "plan.approve", plan, payload={"metrics": _brief(plan)})
    msg = f"{_label(plan, d, db)} was approved by {user.name}."
    notify(db, [plan.proposer_id], "plan.approved", msg, f"plan:{plan.id}", exclude_id=user.id)
    notify(db, recipients(db, f"plan.execute:{plan.type}", d.warehouse_id), "plan.ready",
           msg + " Please confirm execution.", f"plan:{plan.id}", exclude_id=user.id)
    return plan


def reject(db: Session, user: User, plan_id: int, expected_version: int, reason: str) -> Plan:
    plan, d = _lock(db, user, plan_id)
    _authorize(db, user, f"plan.approve:{plan.type}", plan)
    _check_version(plan, expected_version)
    reason = (reason or "").strip()
    if len(reason) < 3:
        raise Invalid("A reason is required to reject a plan")
    if plan.status != S.PROPOSED:
        raise Conflict(f"Plan is {plan.status}, not awaiting approval")
    _move(plan, S.REJECTED)
    db.flush()
    _audit(db, user, "plan.reject", plan, reason=reason)
    notify(db, [plan.proposer_id, *plan.modified_by_ids], "plan.rejected",
           f"{_label(plan, d, db)} was rejected by {user.name}: {reason}", f"plan:{plan.id}", exclude_id=user.id)
    return plan


def _go_stale(db: Session, user: User, plan: Plan, d: Disruption, reasons: list[str]) -> None:
    plan.status = S.STALE
    plan.executor_id = None
    db.flush()
    why = "; ".join(reasons)
    _audit(db, user, "plan.stale", plan, reason=why)
    notify(db, [plan.proposer_id, plan.approver_id, user.id], "plan.stale",
           f"{_label(plan, d, db)} can no longer be executed: {why}. It must be re-evaluated.", f"plan:{plan.id}")
    raise Conflict(f"Plan is now STALE: {why}")


def execute(db: Session, user: User, plan_id: int, expected_version: int, now: datetime | None = None) -> Plan:
    now = now or datetime.now(timezone.utc)
    plan, d = _lock(db, user, plan_id)
    _authorize(db, user, f"plan.execute:{plan.type}", plan)
    _check_version(plan, expected_version)
    if plan.status != S.APPROVED:
        raise Conflict(f"Plan is {plan.status}; only an APPROVED plan can be executed")
    reason = execution_block(user.id, plan.approver_id)
    if reason:
        _audit(db, user, "execution_blocked", plan, reason=reason)
        raise Forbidden(f"You cannot execute this plan: {reason}")
    _move(plan, S.EXECUTING)
    plan.executor_id = user.id
    db.flush()
    reasons = check_preconditions(build_context(db, d, now.date()) if d.status == "active" else None, plan, d)
    if reasons:
        _go_stale(db, user, plan, d, reasons)
    try:
        with db.begin_nested():  # all effects or none
            effects = apply_effects(db, plan, d)
            for st in db.execute(select(PlanStep).where(PlanStep.plan_id == plan.id)).scalars():
                st.status, st.done_at = "done", now
            _move(plan, S.COMPLETED)
            plan.metrics_json = plan.metrics_json | {"executed": effects | {"at": now.isoformat()}}
            db.flush()
    except (ExecutionFailed, StaleDataError) as exc:  # StaleDataError: a stock row changed under us
        db.refresh(plan)  # the savepoint rolled back every change made inside it
        _go_stale(db, user, plan, d, [str(exc) or "stock changed during execution"])
    _audit(db, user, "plan.execute", plan, payload={"effects": effects})
    run_detection(db, now)  # the world changed: re-score risk, resolve or update the disruption
    still = d.status == "active"
    notify(db, [plan.proposer_id, plan.approver_id, *recipients(db, "plan.create")], "plan.executed",
           f"{_label(plan, d, db)} was executed by {user.name}. "
           + ("The disruption is resolved." if not still else "The disruption is still active; check the remaining orders."),
           f"plan:{plan.id}", exclude_id=user.id)
    return plan
