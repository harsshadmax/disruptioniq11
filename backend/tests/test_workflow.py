"""Approval workflow, separation of duties, simulated execution and notifications, end to end over the API."""
import json
from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import select, update

from app.act.rules import approval_block, can_transition, execution_block
from app.audit.service import verify_chain
from app.auth.permissions import PERMISSIONS
from app.config import settings
from app.enums import Role
from app.ingest.webhook import sign
from app.models import (
    AuditLog, Disruption, Inventory, Notification, Order, OrderLine, Plan, PlanStep, Shipment, Sku, User, Warehouse,
)
from app.synth.generator import generate
from app.synth.loader import load_synth

from tests.conftest import auth_headers

TODAY = date.today()
NOW = datetime.now(timezone.utc)


# ---- pure rules ---------------------------------------------------------------------------------------------
def test_state_machine_allows_the_documented_path_only():
    assert can_transition("DRAFT", "PROPOSED") and can_transition("PROPOSED", "APPROVED")
    assert can_transition("PROPOSED", "REJECTED") and can_transition("APPROVED", "EXECUTING")
    assert can_transition("EXECUTING", "COMPLETED") and can_transition("PROPOSED", "PROPOSED")
    assert not can_transition("DRAFT", "APPROVED") and not can_transition("REJECTED", "APPROVED")
    assert not can_transition("COMPLETED", "EXECUTING") and not can_transition("APPROVED", "COMPLETED")
    assert not can_transition("STALE", "PROPOSED") and not can_transition("PROPOSED", "EXECUTING")


def test_separation_of_duties_rules():
    assert approval_block(5, proposer_id=5, modifier_ids=[]) == "approver proposed this plan"
    assert approval_block(7, proposer_id=5, modifier_ids=[6, 7]) == "approver modified this plan"
    assert approval_block(8, proposer_id=5, modifier_ids=[6, 7]) is None
    assert approval_block(8, proposer_id=None, modifier_ids=[]) is None
    assert execution_block(3, approver_id=3) == "executor approved this plan"
    assert execution_block(4, approver_id=3) is None


# ---- fixtures and helpers ------------------------------------------------------------------------------------
@pytest.fixture
def world(db, users):
    load_synth(db, generate(42, TODAY), seed=42)
    return users


def add_user(db, name, role, warehouse=None):
    wh_id = db.execute(select(Warehouse.id).where(Warehouse.name == warehouse)).scalar_one() if warehouse else None
    u = User(name=name, email=f"{name.lower().replace(' ', '.')}@diq.test", password_hash="x", role=role, warehouse_id=wh_id)
    db.add(u)
    db.flush()
    return u


def webhook(client, **over):
    payload = {"occurred_at": NOW.replace(second=0, microsecond=0).isoformat(), "seq": 1} | over
    body = json.dumps(payload).encode()
    return client.post("/webhooks/carrier", content=body,
                       headers={"X-Signature": sign(body, settings.webhook_secret), "Content-Type": "application/json"})


def promised(db, ref):
    db.expire_all()
    return db.execute(select(Shipment).where(Shipment.ref == ref)).scalar_one().promised_eta


def fire_s1(client, db):
    webhook(client, carrier="SeaLink Logistics", shipment_ref="SHP-1042", event_type="delayed",
            new_eta=(promised(db, "SHP-1042") + timedelta(days=6)).isoformat())


def fire_s2(client, db, user):
    webhook(client, carrier="RoadRunner Freight", shipment_ref="SHP-1077", event_type="partial_delivery",
            received=[{"sku": "SKU-006", "qty": 220}], new_eta=(promised(db, "SHP-1077") + timedelta(days=10)).isoformat())
    rows = [{"order_ref": f"ORD-61{i}", "customer": c, "order_date": TODAY.isoformat(),
             "due_date": (TODAY + timedelta(days=d)).isoformat(), "sku": "SKU-006", "warehouse": "Mumbai", "qty": q}
            for i, (c, d, q) in enumerate([("Konkan Fabricators", 4, 40), ("Western Grid Industries", 5, 45),
                                           ("Thane Hardware Mart", 6, 40), ("Sundaram Auto Parts", 8, 35)], 1)]
    client.post("/import/json", headers=auth_headers(user), json={"entity": "orders", "rows": rows})


def plans(client, user, warehouse="Chennai"):
    d = next(d for d in client.get("/disruptions", headers=auth_headers(user)).json() if d["warehouse"] == warehouse)
    return {p["type"]: p for p in client.get(f"/disruptions/{d['id']}/plans", headers=auth_headers(user)).json()}


def act(client, user, plan, action, **body):
    return client.post(f"/plans/{plan['id']}/{action}", headers=auth_headers(user), json={"version": plan["version"], **body})


def ok(resp):
    assert resp.status_code == 200, resp.text
    return resp.json()


def actions(db, *prefixes):
    return [a for a in db.execute(select(AuditLog.action).order_by(AuditLog.id)).scalars()
            if any(a.startswith(p) or a == p for p in prefixes)]


def inbox(client, user):
    return client.get("/notifications", headers=auth_headers(user)).json()


def kinds(client, user):
    return [n["kind"] for n in inbox(client, user)["items"]]


def stock(db, wh, sku="SKU-001"):
    db.expire_all()
    w = db.execute(select(Warehouse.id).where(Warehouse.name == wh)).scalar_one()
    s = db.execute(select(Sku.id).where(Sku.code == sku)).scalar_one()
    return db.get(Inventory, (w, s)).on_hand


# ---- happy path: all five roles -----------------------------------------------------------------------------
def test_reallocate_full_lifecycle_propose_approve_execute(world, db, client):
    fire_s1(client, db)
    analyst, manager, operator = world["ops_analyst"], world["supply_chain_manager"], world["warehouse_operator"]
    plan = plans(client, analyst)["reallocate"]
    qty, bengaluru, chennai = plan["params"]["qty"], stock(db, "Bengaluru"), stock(db, "Chennai")

    p = ok(act(client, analyst, plan, "propose"))
    assert p["status"] == "PROPOSED" and p["proposer_id"] == analyst.id and p["version"] > plan["version"]
    assert "plan.proposed" in kinds(client, manager) and "plan.proposed" not in kinds(client, analyst)

    p = ok(act(client, manager, p, "approve"))
    assert p["status"] == "APPROVED" and p["approver_id"] == manager.id
    assert "plan.approved" in kinds(client, analyst) and "plan.ready" in kinds(client, operator)

    p = ok(act(client, operator, p, "execute"))
    assert p["status"] == "COMPLETED" and p["executor_id"] == operator.id
    assert p["metrics"]["executed"]["moved_units"] == qty and all(s["status"] == "done" for s in p["steps"])
    assert stock(db, "Bengaluru") == bengaluru - qty and stock(db, "Chennai") == chennai + qty
    after = client.get("/disruptions", headers=auth_headers(analyst)).json()  # re-scored: the shipment is still late, but no order is at risk
    assert all(d["newly_at_risk"] == 0 and d["severity"] == "low" for d in after if d["warehouse"] == "Chennai")
    assert "plan.executed" in kinds(client, analyst) and "plan.executed" in kinds(client, manager)
    assert actions(db, "plan.") == ["plan.propose", "plan.approve", "plan.execute"]
    assert verify_chain(db)[0] is True


def test_expedite_goes_to_procurement_and_is_executed_by_the_analyst(world, db, client):
    fire_s1(client, db)
    analyst, procurement = world["ops_analyst"], world["procurement_approver"]
    plan = plans(client, analyst)["expedite"]
    p = ok(act(client, analyst, plan, "propose"))
    assert ok(act(client, procurement, p, "approve"))["status"] == "APPROVED"
    p = client.get(f"/plans/{plan['id']}", headers=auth_headers(analyst)).json()
    p = ok(act(client, analyst, p, "execute"))
    assert p["status"] == "COMPLETED"
    db.expire_all()
    ship = db.execute(select(Shipment).where(Shipment.ref == "SHP-1042")).scalar_one()
    assert ship.current_eta.date().isoformat() == plan["params"]["new_eta"]


def test_alt_supplier_creates_an_inbound_shipment(world, db, client):
    fire_s1(client, db)
    analyst, procurement = world["ops_analyst"], world["procurement_approver"]
    plan = plans(client, analyst)["alt_supplier"]
    p = ok(act(client, procurement, ok(act(client, analyst, plan, "propose")), "approve"))
    ok(act(client, analyst, p, "execute"))
    db.expire_all()
    ship = db.execute(select(Shipment).where(Shipment.ref == f"SHP-ALT-{plan['id']}")).scalar_one()
    assert ship.status == "in_transit" and ship.current_eta.date().isoformat() == plan["params"]["arrival"]


def test_split_ships_the_first_part_and_keeps_the_remainder_open(world, db, client):
    mumbai_op = add_user(db, "Mumbai Op", Role.OPERATOR, "Mumbai")
    fire_s2(client, db, world["ops_analyst"])
    analyst, manager = world["ops_analyst"], world["supply_chain_manager"]
    plan = plans(client, analyst, "Mumbai")["split"]
    assert plan["feasible"]
    line = plan["params"]["lines"][0]
    before = stock(db, "Mumbai", "SKU-006")
    p = ok(act(client, mumbai_op, ok(act(client, manager, ok(act(client, analyst, plan, "propose")), "approve")), "execute"))
    assert p["status"] == "COMPLETED" and p["metrics"]["executed"]["units_shipped_now"] == line["ship_now"]
    db.expire_all()
    ol = db.execute(select(OrderLine).join(Order).where(Order.ref == line["order_ref"])).scalar_one()
    assert ol.qty_allocated == line["ship_now"] and stock(db, "Mumbai", "SKU-006") == before - line["ship_now"]


# ---- who may do what ----------------------------------------------------------------------------------------
@pytest.mark.parametrize("role,allowed", [
    ("supply_chain_manager", True), ("procurement_approver", False), ("administrator", False),
    ("ops_analyst", False), ("warehouse_operator", False)])
def test_only_the_manager_approves_a_reallocation(world, db, client, role, allowed):
    fire_s1(client, db)
    plan = ok(act(client, world["ops_analyst"], plans(client, world["ops_analyst"])["reallocate"], "propose"))
    r = act(client, world[role], plan, "approve")
    assert r.status_code == (200 if allowed else 403), r.text
    if not allowed:
        assert db.execute(select(AuditLog).where(AuditLog.action == "access_denied",
                                                 AuditLog.entity_id == "plan.approve:reallocate")).scalars().first()


@pytest.mark.parametrize("role,allowed", [
    ("procurement_approver", True), ("supply_chain_manager", False), ("administrator", False),
    ("ops_analyst", False), ("warehouse_operator", False)])
def test_only_procurement_approves_an_expedite(world, db, client, role, allowed):
    fire_s1(client, db)
    plan = ok(act(client, world["ops_analyst"], plans(client, world["ops_analyst"])["expedite"], "propose"))
    assert act(client, world[role], plan, "approve").status_code == (200 if allowed else 403)


@pytest.mark.parametrize("role,allowed", [
    ("warehouse_operator", True), ("ops_analyst", False), ("supply_chain_manager", False),
    ("procurement_approver", False), ("administrator", False)])
def test_only_the_warehouse_operator_executes_a_reallocation(world, db, client, role, allowed):
    fire_s1(client, db)
    analyst = world["ops_analyst"]
    p = ok(act(client, world["supply_chain_manager"], ok(act(client, analyst, plans(client, analyst)["reallocate"], "propose")), "approve"))
    assert act(client, world[role], p, "execute").status_code == (200 if allowed else 403)


def test_only_the_analyst_proposes_and_nobody_else_can(world, db, client):
    fire_s1(client, db)
    plan = plans(client, world["ops_analyst"])["reallocate"]
    for role in ("supply_chain_manager", "procurement_approver", "warehouse_operator", "administrator"):
        assert act(client, world[role], plan, "propose").status_code == 403


def test_a_plan_cannot_skip_steps(world, db, client):
    fire_s1(client, db)
    analyst, manager, operator = world["ops_analyst"], world["supply_chain_manager"], world["warehouse_operator"]
    draft = plans(client, analyst)["reallocate"]
    assert act(client, manager, draft, "approve").status_code == 409  # a DRAFT is not awaiting approval
    proposed = ok(act(client, analyst, draft, "propose"))
    assert act(client, operator, proposed, "execute").status_code == 409  # not approved yet


# ---- separation of duties ----------------------------------------------------------------------------------
def test_a_manager_who_modified_the_plan_cannot_approve_it(world, db, client):
    fire_s1(client, db)
    analyst, manager = world["ops_analyst"], world["supply_chain_manager"]
    p = ok(act(client, analyst, plans(client, analyst)["reallocate"], "propose"))
    p = ok(act(client, manager, p, "modify", changes={"qty": 100}))
    assert p["modified_by_ids"] == [manager.id] and p["status"] == "PROPOSED"
    blocked = act(client, manager, p, "approve")
    assert blocked.status_code == 403 and "modified" in blocked.json()["detail"]
    row = db.execute(select(AuditLog).where(AuditLog.action == "approval_blocked")).scalar_one()
    assert row.actor_id == manager.id and "modified" in row.reason
    assert client.get(f"/plans/{p['id']}", headers=auth_headers(manager)).json()["status"] == "PROPOSED"
    other = add_user(db, "Second Manager", Role.MANAGER)  # a different manager can approve the modified plan
    assert ok(act(client, other, p, "approve"))["status"] == "APPROVED"


def test_the_executor_may_not_be_the_approver(world, db, client, monkeypatch):
    monkeypatch.setitem(PERMISSIONS, "plan.execute:reallocate", frozenset({Role.OPERATOR, Role.MANAGER}))
    fire_s1(client, db)
    analyst, manager = world["ops_analyst"], world["supply_chain_manager"]
    p = ok(act(client, manager, ok(act(client, analyst, plans(client, analyst)["reallocate"], "propose")), "approve"))
    r = act(client, manager, p, "execute")
    assert r.status_code == 403 and "approved" in r.json()["detail"]
    assert db.execute(select(AuditLog).where(AuditLog.action == "execution_blocked")).scalar_one().actor_id == manager.id
    assert client.get(f"/plans/{p['id']}", headers=auth_headers(manager)).json()["status"] == "APPROVED"


def test_the_proposer_may_not_approve_even_if_a_role_could(world, db, client, monkeypatch):
    monkeypatch.setitem(PERMISSIONS, "plan.approve:reallocate", frozenset({Role.MANAGER, Role.ANALYST}))
    fire_s1(client, db)
    analyst = world["ops_analyst"]
    p = ok(act(client, analyst, plans(client, analyst)["reallocate"], "propose"))
    r = act(client, analyst, p, "approve")
    assert r.status_code == 403 and "proposed" in r.json()["detail"]
    assert db.execute(select(AuditLog).where(AuditLog.action == "approval_blocked")).scalar_one().actor_id == analyst.id


# ---- concurrency and conflicts -------------------------------------------------------------------------------
def test_double_approve_gives_409(world, db, client):
    fire_s1(client, db)
    analyst, manager = world["ops_analyst"], world["supply_chain_manager"]
    p = ok(act(client, analyst, plans(client, analyst)["reallocate"], "propose"))
    second_manager = add_user(db, "Tab Two", Role.MANAGER)
    assert act(client, manager, p, "approve").status_code == 200  # tab one
    late = act(client, second_manager, p, "approve")  # tab two still holds the old version
    assert late.status_code == 409 and "changed" in late.json()["detail"]
    fresh = client.get(f"/plans/{p['id']}", headers=auth_headers(manager)).json()
    assert act(client, second_manager, fresh, "approve").status_code == 409  # even with the new version: already approved
    assert actions(db, "plan.approve") == ["plan.approve"]


def test_stale_version_on_modify_is_a_conflict(world, db, client):
    fire_s1(client, db)
    analyst, manager = world["ops_analyst"], world["supply_chain_manager"]
    p = ok(act(client, analyst, plans(client, analyst)["reallocate"], "propose"))
    ok(act(client, manager, p, "modify", changes={"qty": 100}))
    assert act(client, add_user(db, "Mgr Two", Role.MANAGER), p, "modify", changes={"qty": 90}).status_code == 409


def test_only_one_plan_in_progress_per_disruption(world, db, client):
    fire_s1(client, db)
    analyst = world["ops_analyst"]
    both = plans(client, analyst)
    ok(act(client, analyst, both["reallocate"], "propose"))
    r = act(client, analyst, both["expedite"], "propose")
    assert r.status_code == 409 and "already in progress" in r.json()["detail"]


def test_an_infeasible_option_cannot_be_proposed(world, db, client):
    fire_s1(client, db)
    analyst = world["ops_analyst"]
    r = act(client, analyst, plans(client, analyst)["split"], "propose")
    assert r.status_code == 422 and "infeasible" in r.json()["detail"]


# ---- reject --------------------------------------------------------------------------------------------------
def test_reject_needs_a_reason_and_frees_the_disruption_for_another_plan(world, db, client):
    fire_s1(client, db)
    analyst, manager = world["ops_analyst"], world["supply_chain_manager"]
    both = plans(client, analyst)
    p = ok(act(client, analyst, both["reallocate"], "propose"))
    assert act(client, manager, p, "reject", reason="no").status_code == 422
    r = ok(act(client, manager, p, "reject", reason="Bengaluru needs that stock for Diwali"))
    assert r["status"] == "REJECTED" and "plan.rejected" in kinds(client, analyst)
    assert act(client, manager, r, "approve").status_code == 409
    assert actions(db, "plan.reject") == ["plan.reject"]
    assert ok(act(client, analyst, both["expedite"], "propose"))["status"] == "PROPOSED"
    assert act(client, world["procurement_approver"], p, "reject", reason="not my plan").status_code == 403


# ---- modify --------------------------------------------------------------------------------------------------
def test_modify_recomputes_metrics_and_creates_a_new_version(world, db, client):
    fire_s1(client, db)
    analyst, manager = world["ops_analyst"], world["supply_chain_manager"]
    p = ok(act(client, analyst, plans(client, analyst)["reallocate"], "propose"))
    m = ok(act(client, manager, p, "modify", changes={"qty": 100}))
    assert m["params"]["qty"] == 100 and m["metrics"]["cost"] == pytest.approx(100 * 4.0)
    assert m["metrics"]["orders_saved"] <= p["metrics"]["orders_saved"] and m["version"] > p["version"]
    assert m["status"] == "PROPOSED" and "plan.modified" in kinds(client, analyst)
    assert m["steps"] and any("100" in s["description"] for s in m["steps"])
    row = db.execute(select(AuditLog).where(AuditLog.action == "plan.modify")).scalar_one()
    assert row.payload_json["changes"] == {"qty": 100} and row.payload_json["after"]["cost"] == m["metrics"]["cost"]


def test_modify_rejects_unknown_or_infeasible_changes(world, db, client):
    fire_s1(client, db)
    analyst, manager = world["ops_analyst"], world["supply_chain_manager"]
    p = ok(act(client, analyst, plans(client, analyst)["reallocate"], "propose"))
    assert act(client, manager, p, "modify", changes={"cost": 1}).status_code == 422
    assert act(client, manager, p, "modify", changes={}).status_code == 422
    assert act(client, manager, p, "modify", changes={"qty": 0}).status_code == 422
    too_much = act(client, manager, p, "modify", changes={"qty": 100000})
    assert too_much.status_code == 422 and "can spare only" in too_much.json()["detail"]
    assert db.execute(select(AuditLog).where(AuditLog.action == "plan.modify_rejected")).scalars().first()
    assert client.get(f"/plans/{p['id']}", headers=auth_headers(manager)).json()["version"] == p["version"]


def test_who_may_modify_which_state(world, db, client):
    fire_s1(client, db)
    analyst, manager, procurement = world["ops_analyst"], world["supply_chain_manager"], world["procurement_approver"]
    draft = plans(client, analyst)["reallocate"]
    assert act(client, world["administrator"], draft, "modify", changes={"qty": 100}).status_code == 403
    assert act(client, procurement, draft, "modify", changes={"qty": 100}).status_code == 403  # drafts: analyst, manager
    d2 = ok(act(client, analyst, draft, "modify", changes={"qty": 120}))
    assert d2["status"] == "DRAFT" and d2["modified_by_ids"] == [analyst.id]
    proposed = ok(act(client, analyst, d2, "propose"))
    r = act(client, analyst, proposed, "modify", changes={"qty": 100})
    assert r.status_code == 403 and db.execute(select(AuditLog).where(AuditLog.action == "modify_blocked")).scalars().first()
    assert act(client, procurement, proposed, "modify", changes={"qty": 100}).status_code == 200


# ---- execution safety ----------------------------------------------------------------------------------------
def test_stock_changed_before_execution_makes_the_plan_stale_and_writes_nothing(world, db, client):
    fire_s1(client, db)
    analyst, manager, operator = world["ops_analyst"], world["supply_chain_manager"], world["warehouse_operator"]
    p = ok(act(client, manager, ok(act(client, analyst, plans(client, analyst)["reallocate"], "propose")), "approve"))
    sku = db.execute(select(Sku.id).where(Sku.code == "SKU-001")).scalar_one()
    wh = db.execute(select(Warehouse.id).where(Warehouse.name == "Bengaluru")).scalar_one()
    inv = db.get(Inventory, (wh, sku))
    inv.on_hand = inv.safety_stock  # somebody else used the surplus after approval
    db.flush()
    chennai_before, bengaluru_before = stock(db, "Chennai"), stock(db, "Bengaluru")
    r = act(client, operator, p, "execute")
    assert r.status_code == 409 and "STALE" in r.json()["detail"]
    final = client.get(f"/plans/{p['id']}", headers=auth_headers(operator)).json()
    assert final["status"] == "STALE" and final["executor_id"] is None
    assert stock(db, "Chennai") == chennai_before and stock(db, "Bengaluru") == bengaluru_before
    assert all(s["status"] == "pending" for s in final["steps"])
    assert actions(db, "plan.stale") == ["plan.stale"]
    assert "plan.stale" in kinds(client, analyst) and "plan.stale" in kinds(client, manager)
    assert act(client, operator, final, "execute").status_code == 409  # a STALE plan stays dead


def test_shipment_eta_changed_after_approval_makes_an_expedite_stale(world, db, client):
    fire_s1(client, db)
    analyst, procurement = world["ops_analyst"], world["procurement_approver"]
    p = ok(act(client, procurement, ok(act(client, analyst, plans(client, analyst)["expedite"], "propose")), "approve"))
    webhook(client, carrier="SeaLink Logistics", shipment_ref="SHP-1042", event_type="delayed", seq=2,
            occurred_at=(NOW + timedelta(hours=1)).isoformat(),
            new_eta=(promised(db, "SHP-1042") + timedelta(days=8)).isoformat())
    eta_before = db.execute(select(Shipment.current_eta).where(Shipment.ref == "SHP-1042")).scalar_one()
    r = act(client, analyst, p, "execute")
    assert r.status_code == 409 and "STALE" in r.json()["detail"]
    db.expire_all()
    assert db.execute(select(Shipment.current_eta).where(Shipment.ref == "SHP-1042")).scalar_one() == eta_before


def test_a_failure_halfway_through_execution_rolls_everything_back(world, db, client, monkeypatch):
    from app.act import execution, service
    from app.act.execution import ExecutionFailed

    def half_done(db_, plan, d):
        execution.apply_effects.__wrapped__(db_, plan, d)  # the real effects run first...
        raise ExecutionFailed("the carrier system rejected the booking")  # ...then it fails

    real = execution.apply_effects
    half_done_wrapper = half_done
    real.__wrapped__ = real
    monkeypatch.setattr(service, "apply_effects", half_done_wrapper)
    fire_s1(client, db)
    analyst, manager, operator = world["ops_analyst"], world["supply_chain_manager"], world["warehouse_operator"]
    p = ok(act(client, manager, ok(act(client, analyst, plans(client, analyst)["reallocate"], "propose")), "approve"))
    before = (stock(db, "Bengaluru"), stock(db, "Chennai"))
    r = act(client, operator, p, "execute")
    assert r.status_code == 409 and "carrier system rejected" in r.json()["detail"]
    assert (stock(db, "Bengaluru"), stock(db, "Chennai")) == before
    assert client.get(f"/plans/{p['id']}", headers=auth_headers(operator)).json()["status"] == "STALE"


def test_a_plan_goes_stale_when_its_disruption_resolves_on_its_own(world, db, client):
    fire_s1(client, db)
    analyst = world["ops_analyst"]
    p = ok(act(client, analyst, plans(client, analyst)["reallocate"], "propose"))
    webhook(client, carrier="SeaLink Logistics", shipment_ref="SHP-1042", event_type="eta_update", seq=2,
            occurred_at=(NOW + timedelta(hours=1)).isoformat(), new_eta=promised(db, "SHP-1042").isoformat())
    now = client.get(f"/plans/{p['id']}", headers=auth_headers(analyst)).json()
    assert now["status"] == "STALE"
    assert "plan.stale" in kinds(client, analyst)


# ---- visibility ---------------------------------------------------------------------------------------------
def test_operators_only_touch_their_own_warehouse(world, db, client):
    mumbai_op = add_user(db, "Mumbai Op", Role.OPERATOR, "Mumbai")
    fire_s1(client, db)
    analyst, manager = world["ops_analyst"], world["supply_chain_manager"]
    p = ok(act(client, manager, ok(act(client, analyst, plans(client, analyst)["reallocate"], "propose")), "approve"))
    assert client.get(f"/plans/{p['id']}", headers=auth_headers(mumbai_op)).status_code == 404
    assert act(client, mumbai_op, p, "execute").status_code == 404
    assert client.get("/plans", headers=auth_headers(mumbai_op)).json() == []
    assert "plan.ready" not in kinds(client, mumbai_op)  # only the destination warehouse's operator is asked
    chennai_op = world["warehouse_operator"]
    assert [x["id"] for x in client.get("/plans", headers=auth_headers(chennai_op)).json()] != []


# ---- notifications ------------------------------------------------------------------------------------------
def test_notifications_are_private_and_can_be_marked_read(world, db, client):
    fire_s1(client, db)
    analyst, manager = world["ops_analyst"], world["supply_chain_manager"]
    assert "disruption.detected" in kinds(client, analyst) and "disruption.detected" in kinds(client, manager)
    assert kinds(client, world["administrator"]) == [] and kinds(client, world["warehouse_operator"]) == []
    box = inbox(client, analyst)
    assert box["unread"] == len(box["items"]) >= 1
    first = box["items"][0]
    assert client.post(f"/notifications/{first['id']}/read", headers=auth_headers(manager)).status_code == 404
    assert client.post(f"/notifications/{first['id']}/read", headers=auth_headers(analyst)).json()["read"] is True
    assert inbox(client, analyst)["unread"] == box["unread"] - 1
    assert client.post("/notifications/read-all", headers=auth_headers(analyst)).json()["unread"] == 0
    assert client.get("/notifications").status_code == 401


def test_overdue_plans_are_flagged_and_approvers_reminded_once(world, db, client):
    fire_s1(client, db)
    analyst, manager = world["ops_analyst"], world["supply_chain_manager"]
    p = ok(act(client, analyst, plans(client, analyst)["reallocate"], "propose"))
    assert p["overdue"] is False
    db.execute(update(Plan).where(Plan.id == p["id"]).values(updated_at=datetime.now(timezone.utc) - timedelta(hours=3)))
    db.expire_all()
    assert client.get(f"/plans/{p['id']}", headers=auth_headers(manager)).json()["overdue"] is True
    assert client.post("/disruptions/detect", headers=auth_headers(analyst)).status_code == 200
    assert kinds(client, manager).count("plan.overdue") == 1
    client.post("/disruptions/detect", headers=auth_headers(analyst))
    assert kinds(client, manager).count("plan.overdue") == 1  # not nagged on every run
    queue = client.get("/plans?state=PROPOSED", headers=auth_headers(manager)).json()
    assert [q["id"] for q in queue] == [p["id"]] and queue[0]["overdue"]


def test_every_workflow_step_is_in_the_audit_log_and_the_chain_verifies(world, db, client):
    fire_s1(client, db)
    analyst, manager, operator = world["ops_analyst"], world["supply_chain_manager"], world["warehouse_operator"]
    p = ok(act(client, analyst, plans(client, analyst)["reallocate"], "propose"))
    ok(act(client, manager, p, "modify", changes={"qty": 100}))
    act(client, manager, p, "approve")  # stale version: not audited as an approval
    p = client.get(f"/plans/{p['id']}", headers=auth_headers(manager)).json()
    act(client, manager, p, "approve")  # the modifier: blocked
    assert actions(db, "plan.", "approval_blocked", "modify_blocked") == ["plan.propose", "plan.modify", "approval_blocked"]
    assert verify_chain(db)[0] is True
