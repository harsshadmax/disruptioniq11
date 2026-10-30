"""Administrator demo controls: each one drives a real guard, and the result lands in the audit log."""
import pytest
from sqlalchemy import func, select

from app.audit.service import verify_chain
from app.enums import Role
from app.models import AuditLog, Plan, Shipment, ShipmentEvent

from tests.conftest import auth_headers
from tests.test_workflow import act, actions, add_user, fire_s1, ok, plans, world  # noqa: F401  (world is a fixture)

CONTROLS = ["replay-duplicate", "stale-event", "self-approval", "double-approve"]


def call(client, user, name):
    return client.post(f"/demo/{name}", headers=auth_headers(user))


def propose(client, world):
    analyst = world[Role.ANALYST.value]
    return ok(act(client, analyst, plans(client, analyst)["reallocate"], "propose"))


@pytest.mark.parametrize("name", CONTROLS)
def test_only_the_administrator_may_use_the_controls(world, client, name):
    for role in Role:
        resp = call(client, world[role.value], name)
        assert (resp.status_code == 403) == (role != Role.ADMIN), (role, resp.text)
    assert client.get("/demo/targets", headers=auth_headers(world[Role.ANALYST.value])).status_code == 403


@pytest.mark.parametrize("name", CONTROLS)
def test_controls_say_what_is_missing_when_there_is_nothing_to_act_on(world, client, name):
    resp = call(client, world[Role.ADMIN.value], name)
    assert resp.status_code == 409 and "first" in resp.json()["detail"].lower()
    assert client.get("/demo/targets", headers=auth_headers(world[Role.ADMIN.value])).json() == {
        "last_event": None, "proposed_plan_id": None, "proposed_plan": None}


def test_replaying_a_duplicate_webhook_changes_nothing_and_is_audited(world, db, client):
    fire_s1(client, db)
    admin = world[Role.ADMIN.value]
    events = db.execute(select(func.count()).select_from(ShipmentEvent)).scalar_one()
    eta = db.execute(select(Shipment.current_eta).where(Shipment.ref == "SHP-1042")).scalar_one()

    r = ok(call(client, admin, "replay-duplicate"))
    assert r["guard_held"] and r["steps"][0]["outcome"] == "duplicate"
    assert db.execute(select(func.count()).select_from(ShipmentEvent)).scalar_one() == events
    db.expire_all()
    assert db.execute(select(Shipment.current_eta).where(Shipment.ref == "SHP-1042")).scalar_one() == eta
    assert actions(db, "webhook.duplicate", "demo.replay_duplicate") == ["webhook.duplicate", "demo.replay_duplicate"]


def test_a_stale_event_is_rejected_every_time_and_the_shipment_keeps_its_state(world, db, client):
    fire_s1(client, db)
    admin = world[Role.ADMIN.value]
    before = db.execute(select(Shipment.last_seq, Shipment.current_eta).where(Shipment.ref == "SHP-1042")).one()
    for _ in range(2):  # a second click must be judged on its sequence number, not collapse into a duplicate
        r = ok(call(client, admin, "stale-event"))
        assert r["guard_held"] and r["steps"][0]["outcome"] == "stale"
    db.expire_all()
    assert db.execute(select(Shipment.last_seq, Shipment.current_eta).where(Shipment.ref == "SHP-1042")).one() == before
    assert actions(db, "webhook.stale", "demo.stale_event") == ["webhook.stale", "demo.stale_event"] * 2


def test_self_approval_by_the_proposer_is_blocked_and_the_plan_is_untouched(world, db, client):
    fire_s1(client, db)
    plan = propose(client, world)
    r = ok(call(client, world[Role.ADMIN.value], "self-approval"))
    assert r["guard_held"] and r["steps"][0]["status_code"] == 403
    db.expire_all()
    assert db.get(Plan, plan["id"]).status == "PROPOSED" and db.get(Plan, plan["id"]).version == plan["version"]
    denied = db.execute(select(AuditLog).where(AuditLog.action == "access_denied")).scalars().all()
    assert denied and denied[-1].role == Role.ANALYST.value  # the proposer's own attempt, not the administrator's
    assert actions(db, "demo.self_approval") == ["demo.self_approval"]


def test_a_manager_who_modified_the_plan_is_blocked_from_approving_it(world, db, client):
    fire_s1(client, db)
    manager = world[Role.MANAGER.value]
    plan = ok(act(client, manager, propose(client, world), "modify", changes={"qty": 100}))
    r = ok(call(client, world[Role.ADMIN.value], "self-approval"))
    assert r["guard_held"] and "modified" in r["steps"][0]["detail"]
    db.expire_all()
    assert db.get(Plan, plan["id"]).status == "PROPOSED"
    assert actions(db, "approval_blocked") == ["approval_blocked"]


def test_double_approve_lets_one_through_and_refuses_the_second_with_409(world, db, client):
    fire_s1(client, db)
    plan = propose(client, world)
    r = ok(call(client, world[Role.ADMIN.value], "double-approve"))
    assert r["guard_held"] and [s["status_code"] for s in r["steps"]] == [200, 409]
    db.expire_all()
    assert db.get(Plan, plan["id"]).status == "APPROVED"
    assert actions(db, "plan.approve", "demo.double_approve") == ["plan.approve", "demo.double_approve"]
    # nothing proposed any more, so the control explains itself instead of doing anything
    assert call(client, world[Role.ADMIN.value], "double-approve").status_code == 409


def test_double_approve_skips_people_who_may_not_approve(world, db, client):
    fire_s1(client, db)
    manager = world[Role.MANAGER.value]
    ok(act(client, manager, propose(client, world), "modify", changes={"qty": 100}))
    # the only manager modified the plan, so nobody is eligible; a second manager makes the demo possible
    assert call(client, world[Role.ADMIN.value], "double-approve").status_code == 409
    other = add_user(db, "Second Manager", Role.MANAGER.value)
    r = ok(call(client, world[Role.ADMIN.value], "double-approve"))
    assert r["guard_held"] and other.name in r["steps"][0]["label"]


def test_demo_runs_leave_a_verifiable_audit_chain(world, db, client):
    fire_s1(client, db)
    propose(client, world)
    admin = world[Role.ADMIN.value]
    for name in ("replay-duplicate", "stale-event", "self-approval", "double-approve"):
        ok(call(client, admin, name))
    rows = client.get("/audit", headers=auth_headers(admin)).json()
    assert {"demo.replay_duplicate", "demo.stale_event", "demo.self_approval", "demo.double_approve"} <= {r["action"] for r in rows}
    assert verify_chain(db)[0]
