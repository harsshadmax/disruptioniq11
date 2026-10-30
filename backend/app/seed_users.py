"""Seed one demo user per role. Idempotent. Run: python -m app.seed_users

Demo credentials (synthetic, local/demo use only): password below for all five users.
"""
import os

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.security import hash_password
from app.config import settings
from app.db import SessionLocal
from app.enums import Role
from app.models import User, Warehouse

_DEFAULT_DEMO_PASSWORD = "Demo@12345"  # public in the README: fine on a laptop, never on a shared deployment
DEMO_PASSWORD = os.environ.get("DEMO_PASSWORD", _DEFAULT_DEMO_PASSWORD)

DEMO_USERS = [
    ("Asha Analyst", "analyst@diq.test", Role.ANALYST, None),
    ("Manoj Manager", "manager@diq.test", Role.MANAGER, None),
    ("Omar Operator", "operator@diq.test", Role.OPERATOR, "Chennai"),
    ("Priya Procurement", "procurement@diq.test", Role.PROCUREMENT, None),
    ("Adam Admin", "admin@diq.test", Role.ADMIN, None),
]


def seed_users(db: Session, password: str = DEMO_PASSWORD, iterations: int = 200_000) -> dict[str, User]:
    out: dict[str, User] = {}
    for name, email, role, wh_name in DEMO_USERS:
        wh_id = None
        if wh_name:
            wh = db.execute(select(Warehouse).where(Warehouse.name == wh_name)).scalar_one_or_none()
            if wh is None:
                wh = Warehouse(name=wh_name, city=wh_name)
                db.add(wh)
                db.flush()
            wh_id = wh.id
        user = db.execute(select(User).where(User.email == email)).scalar_one_or_none()
        if user is None:
            user = User(name=name, email=email, role=role.value, warehouse_id=wh_id,
                        password_hash=hash_password(password, iterations))
            db.add(user)
            db.flush()
        out[role.value] = user
    return out


if __name__ == "__main__":
    if not settings.is_development and DEMO_PASSWORD == _DEFAULT_DEMO_PASSWORD:
        raise SystemExit("Refusing to seed the demo users with the public default password outside development. "
                         "Set DEMO_PASSWORD to a private value first.")
    with SessionLocal() as session:
        users = seed_users(session)
        session.commit()
        print(f"Seeded {len(users)} users (see DEMO_PASSWORD in app/seed_users.py)")
