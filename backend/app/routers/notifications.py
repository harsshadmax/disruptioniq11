from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.auth.deps import get_current_user
from app.db import get_db
from app.models import Notification, User

router = APIRouter(prefix="/notifications", tags=["notifications"])


class NotificationOut(BaseModel):
    id: int
    kind: str
    message: str
    entity_ref: str | None
    created_at: datetime
    read: bool


class Inbox(BaseModel):
    unread: int
    items: list[NotificationOut]


def _out(n: Notification) -> NotificationOut:
    return NotificationOut(id=n.id, kind=n.kind, message=n.message, entity_ref=n.entity_ref, created_at=n.created_at,
                           read=n.read_at is not None)


@router.get("", response_model=Inbox)
def my_notifications(unread_only: bool = False, limit: int = Query(50, ge=1, le=200),
                     user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> Inbox:
    """Always the caller's own notifications: the user id comes from the token, never from the request."""
    q = select(Notification).where(Notification.user_id == user.id)
    if unread_only:
        q = q.where(Notification.read_at.is_(None))
    unread = db.execute(select(func.count(Notification.id)).where(
        Notification.user_id == user.id, Notification.read_at.is_(None))).scalar_one()
    rows = db.execute(q.order_by(Notification.id.desc()).limit(limit)).scalars().all()
    return Inbox(unread=unread, items=[_out(n) for n in rows])


@router.post("/read-all", response_model=Inbox)
def read_all(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> Inbox:
    db.execute(update(Notification).where(Notification.user_id == user.id, Notification.read_at.is_(None))
               .values(read_at=datetime.now(timezone.utc)))
    db.commit()
    return my_notifications(False, 50, user, db)


@router.post("/{notification_id}/read", response_model=NotificationOut)
def mark_read(notification_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> NotificationOut:
    n = db.get(Notification, notification_id)
    if n is None or n.user_id != user.id:  # someone else's notification looks like a missing one
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Notification not found")
    if n.read_at is None:
        n.read_at = datetime.now(timezone.utc)
        db.commit()
    return _out(n)
