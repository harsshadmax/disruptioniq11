import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.audit.service import write_audit
from app.auth.permissions import can
from app.auth.security import decode_token
from app.db import get_db
from app.models import User

_bearer = HTTPBearer(auto_error=False)


def get_current_user(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_db),
) -> User:
    unauthorized = HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")
    if creds is None:
        raise unauthorized
    try:
        payload = decode_token(creds.credentials)
        user_id = int(payload["sub"])
    except (jwt.PyJWTError, KeyError, ValueError):
        raise unauthorized
    user = db.get(User, user_id)  # the role always comes from the DB, never from the token
    if user is None or not user.is_active:
        raise unauthorized
    return user


def require(permission: str):
    """Route dependency: 403 (and an audit row) unless the caller's role holds `permission`."""

    def dependency(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> User:
        if not can(user.role, permission):
            write_audit(
                db, actor_id=user.id, role=user.role, action="access_denied",
                entity_type="permission", entity_id=permission, reason="role lacks permission",
            )
            db.commit()
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Your role is not allowed to do this")
        return user

    dependency.permission = permission  # lets the matrix test discover every protected route
    return dependency
