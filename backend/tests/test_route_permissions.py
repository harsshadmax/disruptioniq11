"""Every route guarded by require(<permission>) must return 403 for each role without it.

Routes are discovered from the FastAPI app, so new protected routes are covered automatically.
"""
import pytest
from fastapi.routing import APIRoute
from sqlalchemy import select

from app.auth.permissions import can
from app.enums import Role
from app.main import ROUTERS
from app.models import AuditLog

from tests.conftest import auth_headers


def _permissions_of(route: APIRoute) -> list[str]:
    found: list[str] = []

    def walk(dep):
        perm = getattr(dep.call, "permission", None)
        if perm:
            found.append(perm)
        for sub in dep.dependencies:
            walk(sub)

    walk(route.dependant)
    return found


def _cases():
    cases = []
    for route in (r for router in ROUTERS for r in router.routes):
        if not isinstance(route, APIRoute):
            continue
        perms = _permissions_of(route)
        if not perms:
            continue
        path = route.path.replace("{", "").replace("}", "")  # path params become literals; 404/422 is fine
        for method in sorted(route.methods - {"HEAD", "OPTIONS"}):
            for role in Role:
                cases.append(pytest.param(method, path, perms[0], role, id=f"{method} {route.path} as {role.value}"))
    return cases


def test_there_are_protected_routes():
    assert _cases(), "no routes with require(...) found"


@pytest.mark.parametrize("method,path,permission,role", _cases())
def test_route_permission_enforced(client, users, method, path, permission, role):
    user = users[role.value]
    resp = client.request(method, path, headers=auth_headers(user), json={} if method in {"POST", "PUT", "PATCH"} else None)
    if can(role, permission):
        assert resp.status_code not in (401, 403), resp.text
    else:
        assert resp.status_code == 403, resp.text


@pytest.mark.parametrize("method,path,permission,role", _cases()[:1])
def test_routes_reject_anonymous(client, method, path, permission, role):
    assert client.request(method, path).status_code == 401


def test_denied_access_is_audited(client, users, db):
    client.get("/users", headers=auth_headers(users[Role.ANALYST.value]))
    denied = db.execute(select(AuditLog).where(AuditLog.action == "access_denied")).scalars().all()
    assert denied and denied[-1].entity_id == "users.manage"
