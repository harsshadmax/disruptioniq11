"""Approval deadline (blueprint 7.7): plans waiting longer than the SLA are re-notified to their approvers."""
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.enums import PlanStatus
from app.models import Plan
from app.notify.service import already_notified_since, notify, recipients


def remind_overdue(db: Session, now: datetime | None = None) -> list[int]:
    """Re-notify approvers of overdue PROPOSED plans, at most once per SLA window. Returns the plan ids reminded."""
    now = now or datetime.now(timezone.utc)
    window = timedelta(hours=settings.approval_sla_hours)
    reminded = []
    for p in db.execute(select(Plan).where(Plan.status == PlanStatus.PROPOSED, Plan.updated_at < now - window)).scalars():
        ref = f"plan:{p.id}"
        who = [u for u in recipients(db, f"plan.approve:{p.type}")
               if not already_notified_since(db, u.id, "plan.overdue", ref, now - window)]
        if who:
            hours = (now - p.updated_at).total_seconds() / 3600
            notify(db, who, "plan.overdue", f"Plan #{p.id} has waited {hours:.1f} hours for approval "
                   f"(limit {settings.approval_sla_hours:g}).", ref)
            reminded.append(p.id)
    return reminded
