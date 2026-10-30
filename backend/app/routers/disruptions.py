from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import false, select
from sqlalchemy.orm import Session

from app.act.views import PlanOut, plans_out
from app.audit.service import write_audit
from app.auth.deps import require
from app.db import get_db
from app.detect.service import run_detection
from app.enums import Role
from app.impact.allocation import FULL
from app.impact.service import analyze, load_world
from app.models import (
    Customer, Disruption, Order, OrderRisk, Plan, Shipment, Sku, Supplier, User, Warehouse,
)
from app.options.service import generate_plans

router = APIRouter(prefix="/disruptions", tags=["disruptions"])


class DisruptionOut(BaseModel):
    id: int
    type: str
    severity: str
    status: str
    detected_at: datetime
    summary: str | None
    warehouse: str
    sku_code: str
    sku_name: str
    shipment_ref: str | None
    supplier: str | None
    orders_at_risk: int
    newly_at_risk: int
    penalty_exposure: float


class ImpactLine(BaseModel):
    order_ref: str
    customer: str
    tier: str
    due_date: date
    qty: int
    before: str
    after: str
    covered_after: int
    newly_at_risk: bool


class Impact(BaseModel):
    covered_before: int
    covered_after: int
    newly_at_risk: int
    lines: list[ImpactLine]


class DisruptionDetail(DisruptionOut):
    promised_eta: datetime | None
    current_eta: datetime | None
    impact: Impact


class RiskFactor(BaseModel):
    name: str
    value: float
    weight: float
    points: float
    text: str


class RankedOrder(BaseModel):
    rank: int
    order_id: int
    order_ref: str
    customer: str
    tier: str
    due_date: date
    score: float
    band: str
    newly_at_risk: bool
    status_before: str
    status_after: str
    uncovered_qty: int
    order_qty: int
    sla_penalty: float
    earliest_fulfil: date | None
    factors: list[RiskFactor]


class DetectionResult(BaseModel):
    created: list[int]
    updated: list[int]
    resolved: list[int]
    unchanged: list[int]


def _visible(user: User, d: Disruption) -> bool:
    return user.role != Role.OPERATOR or (user.warehouse_id is not None and d.warehouse_id == user.warehouse_id)


def _out(db: Session, d: Disruption, risks: list[OrderRisk]) -> dict:
    ship = db.get(Shipment, d.shipment_id) if d.shipment_id else None
    sup = db.get(Supplier, ship.supplier_id) if ship else None
    sku, wh = db.get(Sku, d.sku_id), db.get(Warehouse, d.warehouse_id)
    return dict(
        id=d.id, type=d.type, severity=d.severity, status=d.status, detected_at=d.detected_at, summary=d.summary_text,
        warehouse=wh.name, sku_code=sku.code, sku_name=sku.name, shipment_ref=ship.ref if ship else None,
        supplier=sup.name if sup else None, orders_at_risk=len(risks),
        newly_at_risk=sum(1 for r in risks if r.factors_json.get("newly_at_risk")),
        penalty_exposure=sum(float(r.factors_json.get("sla_penalty", 0)) for r in risks))


def _risks(db: Session, ids: list[int]) -> dict[int, list[OrderRisk]]:
    out: dict[int, list[OrderRisk]] = {i: [] for i in ids}
    if ids:
        for r in db.execute(select(OrderRisk).where(OrderRisk.disruption_id.in_(ids)).order_by(OrderRisk.rank)).scalars():
            out[r.disruption_id].append(r)
    return out


def _get(db: Session, user: User, disruption_id: int) -> Disruption:
    d = db.get(Disruption, disruption_id)
    if d is None or not _visible(user, d):  # an operator never learns that another warehouse's record exists
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Disruption not found")
    return d


@router.get("", response_model=list[DisruptionOut])
def list_disruptions(
    state: str = Query("active", pattern="^(active|resolved|all)$"),
    user: User = Depends(require("view")), db: Session = Depends(get_db),
) -> list[dict]:
    q = select(Disruption).order_by(Disruption.detected_at.desc(), Disruption.id.desc())
    if state != "all":
        q = q.where(Disruption.status == state)
    if user.role == Role.OPERATOR:  # an operator's warehouse filter lives in the query itself
        q = q.where(Disruption.warehouse_id == user.warehouse_id) if user.warehouse_id is not None else q.where(false())
    rows = list(db.execute(q).scalars())
    risks = _risks(db, [d.id for d in rows])
    return [_out(db, d, risks[d.id]) for d in rows]


@router.post("/detect", response_model=DetectionResult)
def detect_now(user: User = Depends(require("detect.run")), db: Session = Depends(get_db)) -> DetectionResult:
    report = run_detection(db)
    db.commit()
    return DetectionResult(created=report.created, updated=report.updated, resolved=report.resolved,
                           unchanged=report.unchanged)


@router.get("/{disruption_id}", response_model=DisruptionDetail)
def get_disruption(disruption_id: int, user: User = Depends(require("view")), db: Session = Depends(get_db)) -> dict:
    d = _get(db, user, disruption_id)
    out = _out(db, d, _risks(db, [d.id])[d.id])
    cell = load_world(db, only=(d.warehouse_id, d.sku_id)).get((d.warehouse_id, d.sku_id))
    lines: list[ImpactLine] = []
    promised = current = None
    if cell is not None:
        a = analyze(cell, datetime.now(timezone.utc).date())
        for ln in sorted(cell.lines, key=lambda x: (x.due_date, x.line_id)):
            b, af = a.before[ln.line_id], a.after[ln.line_id]
            lines.append(ImpactLine(order_ref=ln.order_ref, customer=ln.customer, tier=ln.tier, due_date=ln.due_date,
                                    qty=ln.qty, before=b.status, after=af.status, covered_after=af.covered_qty,
                                    newly_at_risk=ln.line_id in a.newly_at_risk))
        trig = next((ib for ib in cell.inbound if ib.shipment_id == d.shipment_id), None)
        if trig:
            promised, current = trig.promised_eta, trig.current_eta
    out["promised_eta"], out["current_eta"] = promised, current
    out["impact"] = Impact(
        covered_before=sum(1 for x in lines if x.before == FULL), covered_after=sum(1 for x in lines if x.after == FULL),
        newly_at_risk=sum(1 for x in lines if x.newly_at_risk), lines=lines)
    return out


@router.get("/{disruption_id}/orders", response_model=list[RankedOrder])
def ranked_orders(disruption_id: int, user: User = Depends(require("view")), db: Session = Depends(get_db)) -> list[RankedOrder]:
    d = _get(db, user, disruption_id)
    rows = db.execute(
        select(OrderRisk, Order, Customer).join(Order, Order.id == OrderRisk.order_id)
        .join(Customer, Customer.id == Order.customer_id)
        .where(OrderRisk.disruption_id == d.id).order_by(OrderRisk.rank)).all()
    out = []
    for r, o, c in rows:
        f = r.factors_json
        out.append(RankedOrder(
            rank=r.rank, order_id=o.id, order_ref=o.ref, customer=c.name, tier=c.tier, due_date=o.due_date,
            score=r.score, band=r.band, newly_at_risk=f["newly_at_risk"], status_before=f["status_before"],
            status_after=f["status_after"], uncovered_qty=f["uncovered_qty"], order_qty=f["order_qty"],
            sla_penalty=f["sla_penalty"], earliest_fulfil=f["earliest_fulfil"], factors=f["factors"]))
    return out


def _plans_of(db: Session, disruption_id: int) -> list[PlanOut]:
    plans = db.execute(select(Plan).where(Plan.disruption_id == disruption_id)
                       .where(Plan.status != "CANCELLED")).scalars().all()
    plans.sort(key=lambda p: (p.metrics_json.get("rank", 99), p.id))
    return plans_out(db, plans)


@router.get("/{disruption_id}/plans", response_model=list[PlanOut])
def list_plans(disruption_id: int, user: User = Depends(require("view")), db: Session = Depends(get_db)) -> list[PlanOut]:
    d = _get(db, user, disruption_id)
    return _plans_of(db, d.id)


@router.post("/{disruption_id}/plans/generate", response_model=list[PlanOut])
def regenerate_plans(disruption_id: int, user: User = Depends(require("plan.create")),
                     db: Session = Depends(get_db)) -> list[PlanOut]:
    d = _get(db, user, disruption_id)
    if d.status != "active":
        raise HTTPException(status.HTTP_409_CONFLICT, "Disruption is resolved")
    plans = generate_plans(db, d)
    write_audit(db, actor_id=user.id, role=user.role, action="plans.generate", entity_type="disruption",
                entity_id=d.id, payload={"plans": len(plans), "feasible": sum(1 for p in plans if p.metrics_json["feasible"])})
    db.commit()
    return _plans_of(db, d.id)
