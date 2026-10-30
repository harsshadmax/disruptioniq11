"""Response shapes for plans, shared by the disruptions and plans routers."""
from datetime import datetime, timedelta, timezone

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.permissions import PERMISSIONS
from app.config import settings
from app.enums import PlanStatus
from app.models import Disruption, Plan, PlanStep, Sku, Warehouse


class StepOut(BaseModel):
    seq: int
    description: str
    status: str


class PlanOut(BaseModel):
    id: int
    disruption_id: int
    disruption_type: str
    warehouse: str
    sku_code: str
    type: str
    status: str
    version: int
    feasible: bool
    recommended: bool
    ai_rationale: str | None
    overdue: bool
    reasons: list[str]
    params: dict
    metrics: dict
    steps: list[StepOut]
    approver_roles: list[str]
    executor_roles: list[str]
    proposer_id: int | None
    modified_by_ids: list[int]
    approver_id: int | None
    executor_id: int | None
    updated_at: datetime


def is_overdue(plan: Plan, now: datetime | None = None) -> bool:
    now = now or datetime.now(timezone.utc)
    return plan.status == PlanStatus.PROPOSED and now - plan.updated_at > timedelta(hours=settings.approval_sla_hours)


def plans_out(db: Session, plans: list[Plan], now: datetime | None = None) -> list[PlanOut]:
    if not plans:
        return []
    steps: dict[int, list[PlanStep]] = {p.id: [] for p in plans}
    for st in db.execute(select(PlanStep).where(PlanStep.plan_id.in_(steps)).order_by(PlanStep.seq)).scalars():
        steps[st.plan_id].append(st)
    dis = {d.id: d for d in db.execute(select(Disruption).where(Disruption.id.in_({p.disruption_id for p in plans}))).scalars()}
    wh = {w.id: w.name for w in db.execute(select(Warehouse)).scalars()}
    sku = {s.id: s.code for s in db.execute(select(Sku)).scalars()}
    out = []
    for p in plans:
        m, d = p.metrics_json, dis[p.disruption_id]
        out.append(PlanOut(
            id=p.id, disruption_id=p.disruption_id, disruption_type=d.type, warehouse=wh[d.warehouse_id],
            sku_code=sku[d.sku_id], type=p.type, status=p.status, version=p.version, feasible=m.get("feasible", False),
            recommended=m.get("recommended", False), ai_rationale=p.ai_rationale, overdue=is_overdue(p, now), reasons=m.get("reasons", []),
            params=p.params_json, metrics=m,
            steps=[StepOut(seq=s.seq, description=s.description, status=s.status) for s in steps[p.id]],
            approver_roles=sorted(PERMISSIONS.get(f"plan.approve:{p.type}", [])),
            executor_roles=sorted(PERMISSIONS.get(f"plan.execute:{p.type}", [])),
            proposer_id=p.proposer_id, modified_by_ids=list(p.modified_by_ids or []), approver_id=p.approver_id,
            executor_id=p.executor_id, updated_at=p.updated_at))
    return out
