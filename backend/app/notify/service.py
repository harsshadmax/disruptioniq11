"""In-app notifications."""
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.permissions import can
from app.enums import Role
from app.models import Notification, User


def recipients(db: Session, permission: str, warehouse_id: int | None = None) -> list[User]:
    """Active users whose role holds `permission`; operators only when assigned to `warehouse_id`."""
    out = []
    for u in db.execute(select(User).where(User.is_active.is_(True)).order_by(User.id)).scalars():
        if not can(u.role, permission):
            continue
        if u.role == Role.OPERATOR and (warehouse_id is None or u.warehouse_id != warehouse_id):
            continue
        out.append(u)
    return out


def notify(db: Session, users: list[User | int | None], kind: str, message: str, entity_ref: str | None = None,
           exclude_id: int | None = None) -> int:
    """One notification per distinct user (the actor themself is skipped via exclude_id)."""
    ids = []
    for u in users:
        uid = u.id if isinstance(u, User) else u
        if uid is not None and uid != exclude_id and uid not in ids:
            ids.append(uid)
    db.add_all([Notification(user_id=i, kind=kind, message=message[:2000], entity_ref=entity_ref) for i in ids])
    db.flush()
    return len(ids)


def already_notified_since(db: Session, user_id: int, kind: str, entity_ref: str, since: datetime) -> bool:
    return db.execute(select(Notification.id).where(
        Notification.user_id == user_id, Notification.kind == kind, Notification.entity_ref == entity_ref,
        Notification.created_at >= since)).first() is not None
