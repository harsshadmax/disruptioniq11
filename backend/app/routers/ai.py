from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.ai import client, service
from app.auth.deps import require
from app.db import get_db
from app.models import Disruption, User

router = APIRouter(prefix="/ai", tags=["ai"])


class AiStatus(BaseModel):
    enabled: bool
    model: str | None


class TextOut(BaseModel):
    text: str
    source: str  # "ai" or "template"
    fallback_reason: str | None


class RecommendationOut(BaseModel):
    plan_id: int
    plan_type: str
    rationale: str
    source: str
    fallback_reason: str | None


def _active(db: Session, disruption_id: int) -> Disruption:
    d = db.get(Disruption, disruption_id)
    if d is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Disruption not found")
    return d


@router.get("/status", response_model=AiStatus)
def ai_status(user: User = Depends(require("view"))) -> AiStatus:
    """Whether AI text is switched on. Everything works either way: without a key the templates are used."""
    return AiStatus(enabled=client.enabled(), model=client.model_name() if client.enabled() else None)


@router.post("/disruptions/{disruption_id}/summary", response_model=TextOut)
def summarize(disruption_id: int, user: User = Depends(require("ai.use")), db: Session = Depends(get_db)) -> TextOut:
    d = _active(db, disruption_id)
    r = service.summarize(db, user, d)
    db.commit()
    return TextOut(text=r.text, source=r.source, fallback_reason=r.reason)


@router.post("/disruptions/{disruption_id}/recommend", response_model=RecommendationOut)
def recommend(disruption_id: int, user: User = Depends(require("ai.use")), db: Session = Depends(get_db)) -> RecommendationOut:
    d = _active(db, disruption_id)
    if d.status != "active":
        raise HTTPException(status.HTTP_409_CONFLICT, "Disruption is resolved")
    found = service.recommend(db, user, d)
    if found is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "There is no feasible plan to recommend")
    choice, plan = found
    db.commit()
    return RecommendationOut(plan_id=plan.id, plan_type=plan.type, rationale=choice.rationale, source=choice.source,
                             fallback_reason=choice.reason)


@router.post("/disruptions/{disruption_id}/orders/{order_id}/explain", response_model=TextOut)
def explain(disruption_id: int, order_id: int, user: User = Depends(require("ai.use")),
            db: Session = Depends(get_db)) -> TextOut:
    r = service.explain(db, _active(db, disruption_id), order_id)
    if r is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Order is not part of this disruption")
    return TextOut(text=r.text, source=r.source, fallback_reason=r.reason)
