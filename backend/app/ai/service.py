"""Glue between the database and the AI functions: builds the computed-facts JSON, stores the text, audits the call.

Nothing here changes inventory, deadlines, risk scores, plan metrics, permissions or plan status.
"""
import re

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.ai import functions
from app.ai.functions import AiChoice, AiText
from app.audit.service import write_audit
from app.detect.rules import delay_days
from app.detect.summary import template_summary
from app.enums import PlanStatus
from app.models import Disruption, Order, OrderRisk, Plan, Shipment, Sku, Supplier, User, Warehouse

CANDIDATE_STATUSES = (PlanStatus.DRAFT, PlanStatus.PROPOSED)
_CONTROL = re.compile(r"[\x00-\x1f\x7f<>]")


def clean(value, limit: int = 80):
    """Imported names are untrusted text: strip control characters and markup, cap the length."""
    return _CONTROL.sub(" ", value)[:limit] if isinstance(value, str) else value


def _risks(db: Session, d: Disruption) -> list[OrderRisk]:
    return list(db.execute(select(OrderRisk).where(OrderRisk.disruption_id == d.id).order_by(OrderRisk.rank)).scalars())


def disruption_facts(db: Session, d: Disruption) -> dict:
    ship = db.get(Shipment, d.shipment_id) if d.shipment_id else None
    sup = db.get(Supplier, ship.supplier_id) if ship else None
    risks = _risks(db, d)
    return dict(
        dtype=d.type, warehouse=clean(db.get(Warehouse, d.warehouse_id).name), sku=clean(db.get(Sku, d.sku_id).code),
        shipment_ref=clean(ship.ref) if ship else None, supplier=clean(sup.name) if sup else None,
        delay_days=delay_days(ship.promised_eta, ship.current_eta) if ship else 0,
        promised=ship.promised_eta.date() if ship else None, current=ship.current_eta.date() if ship else None,
        n_at_risk=len(risks), n_newly=sum(1 for r in risks if r.factors_json.get("newly_at_risk")),
        n_high=sum(1 for r in risks if r.band == "high"),
        penalty_exposure=sum(float(r.factors_json.get("sla_penalty", 0)) for r in risks))


def summarize(db: Session, user: User, d: Disruption) -> AiText:
    facts = disruption_facts(db, d)
    context = {k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in facts.items()} | {"severity": d.severity}
    result = functions.summarize_disruption(context, template_summary(**facts))
    d.summary_text = result.text
    write_audit(db, actor_id=user.id, role=user.role, action="ai.summary", entity_type="disruption", entity_id=d.id,
                payload={"source": result.source, "fallback_reason": result.reason})
    return result


def candidates(db: Session, d: Disruption) -> list[Plan]:
    return list(db.execute(select(Plan).where(Plan.disruption_id == d.id, Plan.status.in_(CANDIDATE_STATUSES))
                           .order_by(Plan.id)).scalars())


def plan_facts(p: Plan) -> dict:
    m = p.metrics_json
    return dict(id=p.id, type=p.type, status=p.status, feasible=bool(m.get("feasible")),
                orders_saved=m.get("orders_saved", 0), orders_still_late=m.get("orders_still_late", 0),
                cost=m.get("cost", 0), penalty_avoided=m.get("penalty_avoided", 0), net_benefit=m.get("net_benefit", 0),
                why_not=[clean(r, 160) for r in m.get("reasons", [])] if not m.get("feasible") else [])


def recommend(db: Session, user: User, d: Disruption) -> tuple[AiChoice, Plan] | None:
    """Ask for a recommendation among the feasible candidate plans and store the rationale on the chosen one."""
    plans = candidates(db, d)
    context = {"type": d.type, "severity": d.severity, "warehouse": clean(db.get(Warehouse, d.warehouse_id).name),
               "sku": clean(db.get(Sku, d.sku_id).code), "orders_at_risk": len(_risks(db, d))}
    choice = functions.recommend([plan_facts(p) for p in plans], context)
    if choice is None:
        return None
    by_id = {p.id: p for p in plans}
    for p in plans:
        # Core UPDATE on purpose: advisory text must not bump the plan version (that would 409 an approver who
        # already loaded the plan) or restart its approval-SLA clock.
        db.execute(update(Plan).where(Plan.id == p.id).values(
            ai_rationale=choice.rationale if p.id == choice.plan_id else None, updated_at=Plan.updated_at))
    db.expire_all()
    write_audit(db, actor_id=user.id, role=user.role, action="ai.recommend", entity_type="disruption", entity_id=d.id,
                payload={"plan_id": choice.plan_id, "source": choice.source, "fallback_reason": choice.reason})
    return choice, by_id[choice.plan_id]


def explain(db: Session, d: Disruption, order_id: int) -> AiText | None:
    row = db.execute(select(OrderRisk, Order).join(Order, Order.id == OrderRisk.order_id)
                     .where(OrderRisk.disruption_id == d.id, OrderRisk.order_id == order_id)).first()
    if row is None:
        return None
    r, o = row
    f = r.factors_json
    facts = {"order_ref": clean(o.ref), "score": r.score, "band": r.band, "newly_at_risk": bool(f.get("newly_at_risk")),
             "status_before": f.get("status_before"), "status_after": f.get("status_after"),
             "order_qty": f.get("order_qty"), "uncovered_qty": f.get("uncovered_qty"),
             "due_date": o.due_date.isoformat(), "earliest_fulfil": f.get("earliest_fulfil"),
             "sla_penalty": f.get("sla_penalty"),
             "factors": [{"name": x["name"], "points": x["points"], "text": x["text"]} for x in f.get("factors", [])]}
    # the customer name is deliberately not sent: the factors already carry what matters
    return functions.explain_order_risk(facts)
