from typing import Callable

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy.orm.exc import StaleDataError

from app.act.errors import WorkflowError
from app.auth.deps import require
from app.db import get_db
from app.demo import service
from app.demo.service import DemoResult, DemoTargets
from app.models import User

router = APIRouter(prefix="/demo", tags=["demo"])


def _run(db: Session, fn: Callable[[], DemoResult]) -> DemoResult:
    try:
        result = fn()
        db.commit()
    except WorkflowError as exc:  # no target to act on; anything audited before the error is kept
        db.commit()
        raise HTTPException(exc.status_code, exc.detail)
    except StaleDataError:
        db.rollback()
        raise HTTPException(409, "The data changed while the demo ran. Try again.")
    return result


@router.get("/targets", response_model=DemoTargets)
def targets(user: User = Depends(require("demo.controls")), db: Session = Depends(get_db)) -> DemoTargets:
    """What the controls would act on right now."""
    return service.targets(db)


@router.post("/replay-duplicate", response_model=DemoResult)
def replay_duplicate(user: User = Depends(require("demo.controls")), db: Session = Depends(get_db)) -> DemoResult:
    return _run(db, lambda: service.replay_duplicate(db, user))


@router.post("/stale-event", response_model=DemoResult)
def stale_event(user: User = Depends(require("demo.controls")), db: Session = Depends(get_db)) -> DemoResult:
    return _run(db, lambda: service.stale_event(db, user))


@router.post("/self-approval", response_model=DemoResult)
def self_approval(user: User = Depends(require("demo.controls")), db: Session = Depends(get_db)) -> DemoResult:
    return _run(db, lambda: service.self_approval(db, user))


@router.post("/double-approve", response_model=DemoResult)
def double_approve(user: User = Depends(require("demo.controls")), db: Session = Depends(get_db)) -> DemoResult:
    return _run(db, lambda: service.double_approve(db, user))
