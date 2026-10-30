"""Scenario 1 and 2 end to end: carrier event -> disruption -> candidate recovery plans over the API."""
import json
from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.config import settings
from app.ingest.webhook import sign
from app.models import AuditLog, Inventory, Plan, PlanStep, Shipment, Sku, Warehouse
from app.synth.generator import generate
from app.synth.loader import load_synth

from tests.conftest import auth_headers

TODAY = date.today()
NOW = datetime.now(timezone.utc)


@pytest.fixture
def world(db, users):
    load_synth(db, generate(42, TODAY), seed=42)
    return users


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


def fire_s2(client, db):
    webhook(client, carrier="RoadRunner Freight", shipment_ref="SHP-1077", event_type="partial_delivery",
            received=[{"sku": "SKU-006", "qty": 220}], new_eta=(promised(db, "SHP-1077") + timedelta(days=10)).isoformat())
    rows = [{"order_ref": f"ORD-61{i}", "customer": c, "order_date": TODAY.isoformat(),
             "due_date": (TODAY + timedelta(days=d)).isoformat(), "sku": "SKU-006", "warehouse": "Mumbai", "qty": q}
            for i, (c, d, q) in enumerate([("Konkan Fabricators", 4, 40), ("Western Grid Industries", 5, 45),
                                           ("Thane Hardware Mart", 6, 40), ("Sundaram Auto Parts", 8, 35)], 1)]
    return rows


def import_rows(client, user, rows):
    return client.post("/import/json", headers=auth_headers(user), json={"entity": "orders", "rows": rows})


def plans_of(client, user, warehouse):
    d = next(d for d in client.get("/disruptions", headers=auth_headers(user)).json() if d["warehouse"] == warehouse)
    return d, client.get(f"/disruptions/{d['id']}/plans", headers=auth_headers(user)).json()


def by_type(plans):
    return {p["type"]: p for p in plans}


def test_scenario_1_offers_reallocate_expedite_and_alt_supplier(world, db, client):
    fire_s1(client, db)
    d, plans = plans_of(client, world["ops_analyst"], "Chennai")
    assert len(plans) == 4 and {p["type"] for p in plans} == {"reallocate", "expedite", "alt_supplier", "split"}
    t = by_type(plans)
    assert t["reallocate"]["feasible"] and t["expedite"]["feasible"] and t["alt_supplier"]["feasible"]
    assert t["reallocate"]["params"]["source_warehouse"] == "Bengaluru"
    assert t["reallocate"]["metrics"]["orders_saved"] == 6 and t["reallocate"]["recommended"]
    assert 0 < t["expedite"]["metrics"]["orders_saved"] < 6
    assert t["alt_supplier"]["params"]["supplier"] == "Deccan Plastics"
    feasible = [p for p in plans if p["feasible"]]
    assert len({(p["metrics"]["cost"], p["metrics"]["orders_saved"]) for p in feasible}) >= 2
    assert sum(1 for p in plans if p["recommended"]) == 1
    # infeasible options are reported, not hidden
    assert not t["split"]["feasible"] and any("partial" in r for r in t["split"]["reasons"])
    assert all(p["status"] == "DRAFT" and p["steps"] for p in feasible)


def test_every_option_names_who_approves_and_who_executes_it(world, db, client):
    fire_s1(client, db)
    _, plans = plans_of(client, world["ops_analyst"], "Chennai")
    t = by_type(plans)
    assert t["reallocate"]["approver_roles"] == ["supply_chain_manager"]
    assert t["reallocate"]["executor_roles"] == ["warehouse_operator"]
    assert t["expedite"]["approver_roles"] == ["procurement_approver"]
    assert t["alt_supplier"]["executor_roles"] == ["ops_analyst"]


def test_scenario_2_shows_split_and_alt_supplier(world, db, client):
    rows = fire_s2(client, db)
    assert import_rows(client, world["ops_analyst"], rows).json()["rows_ok"] == 4
    d, plans = plans_of(client, world["ops_analyst"], "Mumbai")
    t = by_type(plans)
    assert d["type"] == "stock_shortage"
    assert t["split"]["feasible"] and t["alt_supplier"]["feasible"]
    assert t["split"]["params"]["lines"][0]["customer"] == "Thane Hardware Mart"
    assert any("does not accept partial" in x for x in t["split"]["reasons"])  # gold customers refuse
    feasible = [p for p in plans if p["feasible"]]
    assert len(feasible) >= 2 and len({(p["metrics"]["cost"], p["metrics"]["orders_saved"]) for p in feasible}) >= 2
    assert t["reallocate"]["feasible"] and t["reallocate"]["params"]["source_warehouse"] == "Delhi"


def test_no_surplus_anywhere_is_reported_with_a_reason_per_warehouse(world, db, client):
    sku = db.execute(select(Sku).where(Sku.code == "SKU-001")).scalar_one()
    for inv in db.execute(select(Inventory).where(Inventory.sku_id == sku.id)).scalars():
        wh = db.get(Warehouse, inv.warehouse_id)
        if wh.name != "Chennai":
            inv.on_hand = inv.safety_stock  # nothing above safety stock
    db.flush()
    fire_s1(client, db)
    _, plans = plans_of(client, world["ops_analyst"], "Chennai")
    r = by_type(plans)["reallocate"]
    assert not r["feasible"] and len(r["reasons"]) == 3 and all("no surplus" in x for x in r["reasons"])
    assert r["metrics"]["orders_saved"] == 0
    assert by_type(plans)["expedite"]["feasible"]  # the other options are unaffected


def test_plans_are_regenerated_in_place_when_the_situation_changes(world, db, client):
    fire_s1(client, db)
    d, first = plans_of(client, world["ops_analyst"], "Chennai")
    webhook(client, carrier="SeaLink Logistics", shipment_ref="SHP-1042", event_type="delayed", seq=2,
            occurred_at=(NOW + timedelta(hours=1)).isoformat(),
            new_eta=(promised(db, "SHP-1042") + timedelta(days=9)).isoformat())
    _, second = plans_of(client, world["ops_analyst"], "Chennai")
    # drafts keep their ids (anyone holding one is not left pointing at a deleted row) but carry the new numbers
    assert len(second) == 4 and {p["id"] for p in first} == {p["id"] for p in second}
    assert {p["id"]: p["metrics"] for p in first} != {p["id"]: p["metrics"] for p in second}
    assert db.execute(select(Plan).where(Plan.disruption_id == d["id"], Plan.status == "DRAFT")).scalars().all().__len__() == 4


def test_non_draft_plans_survive_regeneration(world, db, client):
    fire_s1(client, db)
    d, plans = plans_of(client, world["ops_analyst"], "Chennai")
    keep = db.get(Plan, plans[0]["id"])
    keep.status = "PROPOSED"
    db.flush()
    r = client.post(f"/disruptions/{d['id']}/plans/generate", headers=auth_headers(world["ops_analyst"]))
    assert r.status_code == 200
    ids = {p["id"] for p in r.json()}
    assert keep.id in ids and len(ids) == 5  # the proposed plan plus four fresh drafts


def test_resolving_the_disruption_cancels_its_drafts(world, db, client):
    fire_s1(client, db)
    d, _ = plans_of(client, world["ops_analyst"], "Chennai")
    webhook(client, carrier="SeaLink Logistics", shipment_ref="SHP-1042", event_type="eta_update", seq=2,
            occurred_at=(NOW + timedelta(hours=1)).isoformat(), new_eta=promised(db, "SHP-1042").isoformat())
    statuses = {p.status for p in db.execute(select(Plan).where(Plan.disruption_id == d["id"])).scalars()}
    assert statuses == {"CANCELLED"}
    assert client.get(f"/disruptions/{d['id']}/plans", headers=auth_headers(world["ops_analyst"])).json() == []
    assert client.post(f"/disruptions/{d['id']}/plans/generate", headers=auth_headers(world["ops_analyst"])).status_code == 409


def test_generating_plans_needs_plan_create_and_is_audited(world, db, client):
    fire_s1(client, db)
    d, _ = plans_of(client, world["ops_analyst"], "Chennai")
    url = f"/disruptions/{d['id']}/plans/generate"
    for role in ("warehouse_operator", "procurement_approver", "administrator"):
        assert client.post(url, headers=auth_headers(world[role])).status_code == 403
    assert client.post(url, headers=auth_headers(world["supply_chain_manager"])).status_code == 200
    assert db.execute(select(AuditLog).where(AuditLog.action == "plans.generate")).scalars().first()


def test_operator_cannot_read_plans_of_another_warehouse(world, db, client):
    fire_s1(client, db)
    rows = fire_s2(client, db)
    import_rows(client, world["ops_analyst"], rows)
    mumbai, _ = plans_of(client, world["ops_analyst"], "Mumbai")
    chennai, _ = plans_of(client, world["ops_analyst"], "Chennai")
    op = world["warehouse_operator"]
    assert client.get(f"/disruptions/{mumbai['id']}/plans", headers=auth_headers(op)).status_code == 404
    assert client.get(f"/disruptions/{chennai['id']}/plans", headers=auth_headers(op)).status_code == 200


def test_feasible_plan_steps_are_stored_in_order(world, db, client):
    fire_s1(client, db)
    _, plans = plans_of(client, world["ops_analyst"], "Chennai")
    for p in plans:
        rows = db.execute(select(PlanStep).where(PlanStep.plan_id == p["id"]).order_by(PlanStep.seq)).scalars().all()
        assert [r.seq for r in rows] == list(range(1, len(rows) + 1))
        assert (len(rows) > 0) == p["feasible"] and all(r.status == "pending" for r in rows)
