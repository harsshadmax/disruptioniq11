"""Phase 9 hardening: the fixes from the code and security review, each pinned by a test."""
import json
import re
from pathlib import Path

import pytest
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.auth import throttle
from app.auth.permissions import PERMISSIONS
from app.config import Settings
from app.enums import Role
from app.models import AuditLog, Disruption, Plan

from tests.conftest import auth_headers
from tests.test_workflow import act, fire_s1, ok, plans, world  # noqa: F401  (world is a fixture)

CAN_TS = Path(__file__).resolve().parents[2] / "frontend" / "lib" / "api" / "types.ts"


# ---- the database refuses what the services already check -----------------------------------------------------
def test_database_refuses_a_second_in_flight_plan_for_one_disruption(world, db, client):
    fire_s1(client, db)
    analyst = world[Role.ANALYST.value]
    drafts = list(plans(client, analyst).values())
    ok(act(client, analyst, drafts[0], "propose"))
    other = db.get(Plan, drafts[1]["id"])
    with pytest.raises(IntegrityError):
        with db.begin_nested():
            other.status = "PROPOSED"  # what a racing request would do after passing the application-level check
            db.flush()


def test_database_refuses_a_second_active_disruption_for_one_cell(world, db, client):
    fire_s1(client, db)
    d = db.execute(select(Disruption).where(Disruption.status == "active")).scalars().first()
    with pytest.raises(IntegrityError):
        with db.begin_nested():
            db.add(Disruption(type=d.type, sku_id=d.sku_id, warehouse_id=d.warehouse_id, status="active"))
            db.flush()


# ---- recomputing options keeps the drafts people are working on --------------------------------------------------
def test_regenerating_plans_keeps_draft_ids_and_a_reviewers_change(world, db, client):
    fire_s1(client, db)
    analyst, manager = world[Role.ANALYST.value], world[Role.MANAGER.value]
    before = plans(client, analyst)
    draft = before["reallocate"]
    changed = ok(act(client, manager, draft, "modify", changes={"qty": 100}))
    d_id = changed["disruption_id"]

    r = client.post(f"/disruptions/{d_id}/plans/generate", headers=auth_headers(analyst))
    assert r.status_code == 200, r.text
    after = {p["type"]: p for p in r.json()}
    assert {t: p["id"] for t, p in after.items()} == {t: p["id"] for t, p in before.items()}
    assert after["reallocate"]["params"]["qty"] == 100 and after["reallocate"]["modified_by_ids"] == [manager.id]
    assert after["expedite"]["version"] == before["expedite"]["version"]  # untouched drafts are not rewritten


# ---- loading one cell gives the same answer as loading the whole world ----------------------------------------------
def test_scoped_world_equals_the_full_world_for_that_cell(world, db, client):
    from app.impact.service import load_world

    def normal(c):  # row order is not part of the contract
        return (c.on_hand, c.safety_stock, sorted(c.lines, key=lambda x: x.line_id),
                sorted(c.inbound, key=lambda x: x.shipment_id))

    fire_s1(client, db)
    full = load_world(db)
    assert full
    for key, cell in full.items():
        scoped = load_world(db, only=key)
        assert set(scoped) <= {key}
        assert normal(scoped[key]) == normal(cell), key


# ---- configuration ---------------------------------------------------------------------------------------------
def test_default_secrets_are_refused_outside_development():
    with pytest.raises(ValidationError):
        Settings(_env_file=None, environment="production")
    with pytest.raises(ValidationError):
        Settings(_env_file=None, environment="production", jwt_secret="a" * 32)  # webhook secret still the default
    assert Settings(_env_file=None, environment="production", jwt_secret="a" * 32, webhook_secret="b" * 32)
    assert Settings(_env_file=None).is_development


@pytest.mark.parametrize("given", ["postgres://u:p@h:5432/d", "postgresql://u:p@h:5432/d", "postgresql+psycopg://u:p@h:5432/d"])
def test_host_style_database_urls_get_the_psycopg3_driver(given):
    assert Settings(_env_file=None, database_url=given).database_url == "postgresql+psycopg://u:p@h:5432/d"


# ---- webhook body cap ---------------------------------------------------------------------------------------------
def test_oversized_webhook_body_is_refused_before_the_signature_check(client):
    big = json.dumps({"pad": "x" * 300_000}).encode()
    r = client.post("/webhooks/carrier", content=big, headers={"Content-Type": "application/json"})
    assert r.status_code == 413


def test_webhook_cap_counts_bytes_even_when_content_length_lies(client):
    def chunks():  # chunked upload: no Content-Length at all
        for _ in range(40):
            yield b"x" * 10_000
    r = client.post("/webhooks/carrier", content=chunks(), headers={"Content-Type": "application/json"})
    assert r.status_code == 413


# ---- login throttle ---------------------------------------------------------------------------------------------
def _login(client, email, password):
    return client.post("/auth/login", json={"email": email, "password": password})


def test_repeated_failed_logins_are_throttled_then_audited_once(world, db, client):
    email = world[Role.ANALYST.value].email
    for _ in range(throttle.MAX_FAILURES):
        assert _login(client, email, "wrong").status_code == 401
    assert _login(client, email, "Test-pass-123").status_code == 429  # even the right password waits
    assert _login(client, email, "Test-pass-123").status_code == 429
    blocked = db.execute(select(AuditLog).where(AuditLog.action == "auth.login_blocked")).scalars().all()
    assert len(blocked) == 1
    throttle.reset_all()
    assert _login(client, email, "Test-pass-123").status_code == 200


def test_a_successful_login_clears_the_email_counter_but_not_the_address_counter(world, client):
    email = world[Role.ANALYST.value].email
    for _ in range(throttle.MAX_FAILURES - 1):
        _login(client, email, "wrong")
    assert _login(client, email, "Test-pass-123").status_code == 200
    assert not throttle.blocked(f"email:{email}")
    # the address keeps its count, so signing in to one account cannot launder guesses against others
    assert _login(client, "other@diq.test", "wrong").status_code == 401  # 8th failure from this address
    assert _login(client, "other@diq.test", "wrong").status_code == 429


def test_throttle_window_expires():
    throttle.record_failure("k", now=0)
    for i in range(throttle.MAX_FAILURES - 1):
        throttle.record_failure("k", now=i)
    assert throttle.blocked("k", now=throttle.MAX_FAILURES)
    assert not throttle.blocked("k", now=throttle.WINDOW_SECONDS + 100)


def test_login_fields_are_length_capped(client):
    assert _login(client, "a" * 500 + "@diq.test", "x").status_code == 422
    assert _login(client, "a@diq.test", "x" * 500).status_code == 422


# ---- the UI's role lists must not drift from the permission matrix ---------------------------------------------
UI_TO_MATRIX = {"runDetection": "detect.run", "importData": "import.run", "propose": "plan.propose",
                "generatePlans": "plan.create", "readAudit": "audit.read", "useAi": "ai.use",
                "demoControls": "demo.controls", "simulate": "simulate.run", "contractView": "contract.view",
                "contractUpload": "contract.upload", "contractConfirm": "contract.confirm"}


def _can_lists() -> dict[str, set[str]]:
    block = re.search(r"export const CAN = \{(.*?)\} as const", CAN_TS.read_text(encoding="utf-8"), re.S).group(1)
    return {m.group(1): set(re.findall(r'"([a-z_]+)"', m.group(2))) for m in re.finditer(r"(\w+):\s*\[(.*?)\]", block, re.S)}


@pytest.mark.parametrize("ui_name,permission", sorted(UI_TO_MATRIX.items()))
def test_frontend_role_list_matches_the_permission_matrix(ui_name, permission):
    assert _can_lists()[ui_name] == {r.value for r in PERMISSIONS[permission]}
