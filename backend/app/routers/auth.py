from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit.service import write_audit
from app.auth import throttle
from app.auth.deps import get_current_user
from app.auth.security import create_access_token, verify_password
from app.db import get_db
from app.models import User

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginRequest(BaseModel):
    email: str = Field(max_length=160)
    password: str = Field(max_length=128)


class UserOut(BaseModel):
    id: int
    name: str
    email: str
    role: str
    warehouse_id: int | None


def user_out(u: User) -> UserOut:
    return UserOut(id=u.id, name=u.name, email=u.email, role=u.role, warehouse_id=u.warehouse_id)


@router.post("/login")
def login(body: LoginRequest, request: Request, db: Session = Depends(get_db)) -> dict:
    email = body.email.strip().lower()
    keys = (f"email:{email}", f"ip:{request.client.host if request.client else '?'}")
    if throttle.blocked(*keys):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many failed sign-ins. Wait a few minutes and try again.")
    user = db.execute(select(User).where(User.email == email)).scalar_one_or_none()
    ok = verify_password(body.password, user.password_hash if user else None)
    if not (ok and user and user.is_active):
        failures = throttle.record_failure(*keys)
        write_audit(
            db, actor_id=None, role=None, action="auth.login_failed",
            entity_type="user", entity_id=None, reason="invalid credentials", payload={"email": email},
        )
        if failures == throttle.MAX_FAILURES:  # one row when the block starts, not one per blocked request
            write_audit(db, actor_id=None, role=None, action="auth.login_blocked", entity_type="user", entity_id=None,
                        reason=f"{failures} failed sign-ins in {throttle.WINDOW_SECONDS // 60} minutes",
                        payload={"email": email})
        db.commit()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid email or password")
    throttle.clear(keys[0])
    write_audit(db, actor_id=user.id, role=user.role, action="auth.login", entity_type="user", entity_id=user.id)
    db.commit()
    return {"access_token": create_access_token(user.id, user.role), "token_type": "bearer", "user": user_out(user)}


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)) -> UserOut:
    return user_out(user)
