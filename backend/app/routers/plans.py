from typing import Callable

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import false, select
from sqlalchemy.orm import Session
from sqlalchemy.orm.exc import StaleDataError

from app.act import service
from app.act.errors import WorkflowError
from app.act.views import PlanOut, plans_out
from app.auth.deps import get_current_user, require
from app.db import get_db
from app.enums import Role
from app.models import Disruption, Plan, User

router = APIRouter(prefix="/plans", tags=["plans"])


class VersionBody(BaseModel):
    version: int = Field(ge=1, description="the plan version you last saw (optimistic lock)")


class ModifyBody(VersionBody):
    changes: dict


class RejectBody(VersionBody):
    reason: str = Field(min_length=3, max_length=500)


def _run(db: Session, fn: Callable[[], Plan]) -> PlanOut:
    """Run one workflow action. Blocked attempts were audited inside the service, so they are committed too."""
    try:
        plan = fn()
        db.commit()
    except WorkflowError as exc:
        db.commit()
        raise HTTPException(exc.status_code, exc.detail)
    except StaleDataError:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "This plan was changed by someone else. Reload and try again.")
    return plans_out(db, [plan])[0]


def _visible(user: User, d: Disruption) -> bool:
    return user.role != Role.OPERATOR or (user.warehouse_id is not None and d.warehouse_id == user.warehouse_id)


@router.get("", response_model=list[PlanOut])
def list_plans(
    state: str | None = Query(None, description="filter by status, e.g. PROPOSED"),
    disruption_id: int | None = None,
    user: User = Depends(require("view")),
    db: Session = Depends(get_db),
) -> list[PlanOut]:
    q = select(Plan).where(Plan.status != "CANCELLED").order_by(Plan.updated_at.desc(), Plan.id.desc())
    if state:
        q = q.where(Plan.status == state.upper())
    if disruption_id:
        q = q.where(Plan.disruption_id == disruption_id)
    if user.role == Role.OPERATOR:  # an operator's warehouse filter lives in the query itself
        mine = select(Disruption.id).where(Disruption.warehouse_id == user.warehouse_id) if user.warehouse_id is not None \
            else select(Disruption.id).where(false())
        q = q.where(Plan.disruption_id.in_(mine))
    return plans_out(db, list(db.execute(q).scalars()))


@router.get("/{plan_id}", response_model=PlanOut)
def get_plan(plan_id: int, user: User = Depends(require("view")), db: Session = Depends(get_db)) -> PlanOut:
    plan = db.get(Plan, plan_id)
    if plan is None or not _visible(user, db.get(Disruption, plan.disruption_id)):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Plan not found")
    return plans_out(db, [plan])[0]


@router.post("/{plan_id}/propose", response_model=PlanOut)
def propose(plan_id: int, body: VersionBody, user: User = Depends(require("plan.propose")),
            db: Session = Depends(get_db)) -> PlanOut:
    return _run(db, lambda: service.propose(db, user, plan_id, body.version))


@router.post("/{plan_id}/modify", response_model=PlanOut)
def modify(plan_id: int, body: ModifyBody, user: User = Depends(require("plan.modify")),
           db: Session = Depends(get_db)) -> PlanOut:
    return _run(db, lambda: service.modify(db, user, plan_id, body.version, body.changes))


# approve / reject / execute: the permission depends on the plan type, so the service checks it (and audits a denial)
@router.post("/{plan_id}/approve", response_model=PlanOut)
def approve(plan_id: int, body: VersionBody, user: User = Depends(get_current_user),
            db: Session = Depends(get_db)) -> PlanOut:
    return _run(db, lambda: service.approve(db, user, plan_id, body.version))


@router.post("/{plan_id}/reject", response_model=PlanOut)
def reject(plan_id: int, body: RejectBody, user: User = Depends(get_current_user),
           db: Session = Depends(get_db)) -> PlanOut:
    return _run(db, lambda: service.reject(db, user, plan_id, body.version, body.reason))


@router.post("/{plan_id}/execute", response_model=PlanOut)
def execute(plan_id: int, body: VersionBody, user: User = Depends(get_current_user),
            db: Session = Depends(get_db)) -> PlanOut:
    return _run(db, lambda: service.execute(db, user, plan_id, body.version))
