"""Build option contexts from the database and keep the DRAFT plans of each disruption up to date."""
from datetime import date, datetime, timezone

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.audit.service import write_audit
from app.enums import PlanStatus
from app.notify.service import notify
from app.impact.service import CellWorld, analyze, load_world
from app.models import Disruption, Plan, PlanStep, Sku, Supplier, SupplierItem, TransferCost, Warehouse
from app.options.base import OptionContext, SupplierOffer
from app.options.generators import generate_options, overrides_from_params, recompute_option


def build_context(db: Session, d: Disruption, today: date, world: dict[tuple[int, int], CellWorld] | None = None
                  ) -> OptionContext | None:
    world = world if world is not None else load_world(db)
    cell = world.get((d.warehouse_id, d.sku_id))
    if cell is None:
        return None
    sku = db.get(Sku, d.sku_id)
    offers = [SupplierOffer(sup.id, sup.name, sup.reliability_score, float(si.unit_price), si.lead_days)
              for si, sup in db.execute(select(SupplierItem, Supplier).join(Supplier, Supplier.id == SupplierItem.supplier_id)
                                        .where(SupplierItem.sku_id == d.sku_id)).all()]
    transfers = {(t.from_warehouse_id, t.to_warehouse_id): (float(t.cost_per_unit), t.transit_days)
                 for t in db.execute(select(TransferCost)).scalars()}
    trigger = next((ib for ib in cell.inbound if ib.shipment_id == d.shipment_id), None)
    return OptionContext(
        today=today, cell=cell, analysis=analyze(cell, today), sku_code=sku.code, unit_cost=float(sku.unit_cost),
        warehouse_names={w.id: w.name for w in db.execute(select(Warehouse)).scalars()},
        sibling_cells={wh: c for (wh, sk), c in world.items() if sk == d.sku_id and wh != d.warehouse_id},
        transfers=transfers, offers=offers, trigger=trigger)


def generate_plans(db: Session, d: Disruption, now: datetime | None = None,
                   world: dict[tuple[int, int], CellWorld] | None = None) -> list[Plan]:
    """Bring the DRAFT plans of a disruption up to date with the world (other statuses are left alone).

    Drafts are updated in place, one per plan type, so their ids survive and a reviewer's modification is kept
    (re-evaluated against today's data) instead of vanishing every time detection runs.
    """
    now = now or datetime.now(timezone.utc)
    drafts = {p.type: p for p in db.execute(
        select(Plan).where(Plan.disruption_id == d.id, Plan.status == PlanStatus.DRAFT).order_by(Plan.id)).scalars()}
    ctx = build_context(db, d, now.date(), world)
    if ctx is None:
        if drafts:
            db.execute(delete(PlanStep).where(PlanStep.plan_id.in_([p.id for p in drafts.values()])))
            db.execute(delete(Plan).where(Plan.id.in_([p.id for p in drafts.values()])))
        return []
    plans = []
    first_feasible = True
    for rank, r in enumerate(generate_options(ctx), start=1):
        plan = drafts.pop(r.type, None)
        if plan is not None and plan.modified_by_ids:
            try:  # keep the reviewer's change if it still works
                kept = recompute_option(ctx, r.type, **overrides_from_params(r.type, plan.params_json))
            except KeyError:
                kept = None
            if kept is not None and kept.feasible:
                r = kept
            else:
                plan.modified_by_ids = []
        metrics = dict(r.metrics) | {"feasible": r.feasible, "reasons": r.reasons, "rank": rank,
                                     "recommended": r.feasible and first_feasible}
        first_feasible = first_feasible and not r.feasible
        if plan is None:
            plan = Plan(disruption_id=d.id, type=r.type, params_json=r.params, metrics_json=metrics,
                        status=PlanStatus.DRAFT, modified_by_ids=[])
            db.add(plan)
            db.flush()
        elif plan.params_json != r.params or plan.metrics_json != metrics:  # untouched drafts keep their version
            plan.params_json, plan.metrics_json = r.params, metrics
            db.flush()
        else:
            plans.append(plan)
            continue
        db.execute(delete(PlanStep).where(PlanStep.plan_id == plan.id))
        if r.feasible:
            db.add_all([PlanStep(plan_id=plan.id, seq=i, description=text[:240]) for i, text in enumerate(r.steps, 1)])
        plans.append(plan)
    for stale in drafts.values():  # a draft of a type that is no longer generated
        db.execute(delete(PlanStep).where(PlanStep.plan_id == stale.id))
        db.delete(stale)
    db.flush()
    return plans


def retire_plans(db: Session, disruption_id: int, why: str) -> None:
    """A disruption resolved on its own: drafts are cancelled and plans awaiting action go STALE."""
    for p in db.execute(select(Plan).where(Plan.disruption_id == disruption_id)).scalars():
        if p.status == PlanStatus.DRAFT:
            p.status = PlanStatus.CANCELLED
        elif p.status in (PlanStatus.PROPOSED, PlanStatus.APPROVED):
            p.status = PlanStatus.STALE
            write_audit(db, actor_id=None, role="system", action="plan.stale", entity_type="plan", entity_id=p.id,
                        reason=why, payload={"type": p.type, "disruption_id": disruption_id})
            notify(db, [p.proposer_id, p.approver_id], "plan.stale", f"Plan #{p.id} is stale: {why}", f"plan:{p.id}")
    db.flush()
