import jwt

from app.auth.security import create_access_token
from app.config import settings
from app.enums import Role
from app.models import AuditLog
from sqlalchemy import select

from tests.conftest import auth_headers


def _login(client, email, password="Test-pass-123"):
    return client.post("/auth/login", json={"email": email, "password": password})


def test_login_success_for_every_role_and_is_audited(client, users, db):
    for role in Role:
        r = _login(client, users[role.value].email)
        assert r.status_code == 200
        body = r.json()
        assert body["user"]["role"] == role.value
        me = client.get("/auth/me", headers={"Authorization": f"Bearer {body['access_token']}"})
        assert me.status_code == 200 and me.json()["email"] == users[role.value].email
    actions = [a for a in db.execute(select(AuditLog.action)).scalars()]
    assert actions.count("auth.login") == len(Role)


def test_login_failure_is_generic_and_audited(client, users, db):
    wrong_pw = _login(client, users[Role.ANALYST.value].email, "nope")
    unknown = _login(client, "nobody@diq.test")
    assert wrong_pw.status_code == unknown.status_code == 401
    assert wrong_pw.json() == unknown.json()  # no user enumeration
    failed = db.execute(select(AuditLog).where(AuditLog.action == "auth.login_failed")).scalars().all()
    assert len(failed) == 2
    assert all("password" not in str(f.payload_json).lower() for f in failed)


def test_me_requires_a_valid_token(client, users):
    assert client.get("/auth/me").status_code == 401
    assert client.get("/auth/me", headers={"Authorization": "Bearer garbage"}).status_code == 401


def test_role_comes_from_db_not_token(client, users):
    analyst = users[Role.ANALYST.value]
    forged = jwt.encode({"sub": str(analyst.id), "role": Role.ADMIN.value}, settings.jwt_secret, algorithm="HS256")
    r = client.get("/users", headers={"Authorization": f"Bearer {forged}"})
    assert r.status_code == 403  # token claims admin, the DB says analyst


def test_token_signed_with_other_key_rejected(client, users):
    bad = jwt.encode({"sub": str(users[Role.ADMIN.value].id)}, "some-other-secret-some-other-secret", algorithm="HS256")
    assert client.get("/auth/me", headers={"Authorization": f"Bearer {bad}"}).status_code == 401


def test_inactive_user_is_locked_out(client, users, db):
    u = users[Role.ANALYST.value]
    token = create_access_token(u.id, u.role)
    u.is_active = False
    db.commit()
    assert client.get("/auth/me", headers={"Authorization": f"Bearer {token}"}).status_code == 401
    assert _login(client, u.email).status_code == 401


def test_admin_creates_user_and_it_is_audited(client, users, db):
    admin = users[Role.ADMIN.value]
    r = client.post(
        "/users",
        headers=auth_headers(admin),
        json={"name": "New Op", "email": "New.Op@diq.test", "password": "Another-pass-1", "role": "warehouse_operator"},
    )
    assert r.status_code == 201 and r.json()["email"] == "new.op@diq.test"
    assert db.execute(select(AuditLog).where(AuditLog.action == "user.create")).scalars().first()
    dup = client.post(
        "/users",
        headers=auth_headers(admin),
        json={"name": "Dup", "email": "new.op@diq.test", "password": "Another-pass-1", "role": "ops_analyst"},
    )
    assert dup.status_code == 409


def test_audit_endpoints_for_allowed_role(client, users):
    manager = users[Role.MANAGER.value]
    assert client.get("/audit", headers=auth_headers(manager)).status_code == 200
    v = client.get("/audit/verify", headers=auth_headers(manager)).json()
    assert v["ok"] is True
