from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit.service import write_audit
from app.auth.deps import require
from app.auth.security import hash_password
from app.db import get_db
from app.enums import Role
from app.models import User, Warehouse
from app.routers.auth import UserOut, user_out

router = APIRouter(prefix="/users", tags=["users"])


class NewUser(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    email: str = Field(min_length=3, max_length=160)
    password: str = Field(min_length=8, max_length=128)
    role: Role
    warehouse_id: int | None = None


@router.get("", response_model=list[UserOut])
def list_users(_: User = Depends(require("users.manage")), db: Session = Depends(get_db)) -> list[UserOut]:
    return [user_out(u) for u in db.execute(select(User).order_by(User.id)).scalars()]


@router.post("", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def create_user(body: NewUser, admin: User = Depends(require("users.manage")), db: Session = Depends(get_db)) -> UserOut:
    email = body.email.strip().lower()
    if db.execute(select(User.id).where(User.email == email)).first():
        raise HTTPException(status.HTTP_409_CONFLICT, "Email already registered")
    if body.warehouse_id is not None and db.get(Warehouse, body.warehouse_id) is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Unknown warehouse_id")
    user = User(name=body.name, email=email, password_hash=hash_password(body.password), role=body.role.value,
                warehouse_id=body.warehouse_id)
    db.add(user)
    db.flush()
    write_audit(db, actor_id=admin.id, role=admin.role, action="user.create", entity_type="user", entity_id=user.id,
                payload={"email": email, "role": user.role})
    db.commit()
    return user_out(user)
