"""End to end: synthetic world -> carrier webhook / import -> detection -> ranked at-risk orders."""
import json
from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.audit.service import verify_chain
from app.config import settings
from app.detect.service import run_detection
from app.ingest.webhook import sign
from app.models import AuditLog, Disruption, Inventory, OrderRisk, Shipment, Sku, Warehouse
from app.synth.generator import generate
from app.synth.loader import load_synth

from tests.conftest import auth_headers

TODAY = date.today()  # detection runs on the real clock, so the world is built relative to it
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


def delay_s1(client, db, days=6, **over):
    return webhook(client, carrier="SeaLink Logistics", shipment_ref="SHP-1042", event_type="delayed",
                   new_eta=(promised(db, "SHP-1042") + timedelta(days=days)).isoformat(), **over)


def listing(client, user, state="active"):
    return client.get(f"/disruptions?state={state}", headers=auth_headers(user)).json()


def test_a_healthy_world_has_no_disruptions(world, db, client):
    report = run_detection(db)
    assert not report.changed and not report.created
    assert listing(client, world["ops_analyst"]) == []


def test_detection_is_idempotent(world, db, client):
    delay_s1(client, db)
    before = db.execute(select(AuditLog.id)).all()
    report = run_detection(db)
    assert report.unchanged and not report.changed
    assert db.execute(select(AuditLog.id)).all() == before  # no audit noise when nothing changed


def test_scenario_1_webhook_creates_a_disruption_with_ranked_orders(world, db, client):
    assert delay_s1(client, db).json()["outcome"] == "applied"
    (d,) = listing(client, world["ops_analyst"])
    assert (d["type"], d["warehouse"], d["sku_code"], d["shipment_ref"], d["supplier"]) == (
        "late_shipment", "Chennai", "SKU-001", "SHP-1042", "Coastal Polymers")
    assert 5 <= d["newly_at_risk"] <= 7 and d["orders_at_risk"] >= d["newly_at_risk"] and d["severity"] == "high"
    assert "SHP-1042" in d["summary"] and "6 days late" in d["summary"] and "newly at risk" in d["summary"]

    orders = client.get(f"/disruptions/{d['id']}/orders", headers=auth_headers(world["ops_analyst"])).json()
    assert len(orders) == d["orders_at_risk"]
    assert [o["rank"] for o in orders] == list(range(1, len(orders) + 1))
    scores = [o["score"] for o in orders]
    assert scores == sorted(scores, reverse=True)
    for o in orders:
        assert o["status_after"] != "full" and o["status_before"] == "full" and o["newly_at_risk"]
        assert {f["name"] for f in o["factors"]} == {"shortfall", "time", "tier", "penalty", "supplier"}
        assert sum(f["points"] for f in o["factors"]) == pytest.approx(o["score"], abs=0.2)
    assert {o["tier"] for o in orders} >= {"gold", "silver", "bronze"}


def test_detail_shows_before_versus_after_coverage(world, db, client):
    delay_s1(client, db)
    (d,) = listing(client, world["ops_analyst"])
    detail = client.get(f"/disruptions/{d['id']}", headers=auth_headers(world["supply_chain_manager"])).json()
    imp = detail["impact"]
    assert imp["covered_before"] == 7 and imp["covered_after"] == 1 and imp["newly_at_risk"] == 6
    assert len(imp["lines"]) == 7
    assert detail["current_eta"] > detail["promised_eta"]
    safe = [ln for ln in imp["lines"] if not ln["newly_at_risk"]]
    assert len(safe) == 1 and safe[0]["after"] == "full"


def test_duplicate_and_stale_events_do_not_create_second_disruptions(world, db, client):
    delay_s1(client, db)
    assert delay_s1(client, db).json()["outcome"] == "duplicate"
    stale = webhook(client, carrier="SeaLink Logistics", shipment_ref="SHP-1042", event_type="eta_update", seq=1,
                    new_eta=promised(db, "SHP-1042").isoformat(), occurred_at=(NOW - timedelta(hours=2)).isoformat())
    assert stale.json()["outcome"] == "stale"
    assert len(listing(client, world["ops_analyst"])) == 1


def test_recovery_resolves_the_disruption_and_it_is_audited(world, db, client):
    delay_s1(client, db)
    webhook(client, carrier="SeaLink Logistics", shipment_ref="SHP-1042", event_type="eta_update", seq=2,
            new_eta=promised(db, "SHP-1042").isoformat(), occurred_at=(NOW + timedelta(hours=1)).isoformat())
    assert listing(client, world["ops_analyst"]) == []
    (resolved,) = listing(client, world["ops_analyst"], state="resolved")
    assert resolved["status"] == "resolved"
    actions = [a for a in db.execute(select(AuditLog.action)).scalars() if a.startswith("disruption.")]
    assert actions == ["disruption.detected", "disruption.resolved"]
    assert verify_chain(db)[0] is True


def test_scenario_2_partial_delivery_then_demand_burst_escalates_to_stock_shortage(world, db, client):
    webhook(client, carrier="RoadRunner Freight", shipment_ref="SHP-1077", event_type="partial_delivery",
            received=[{"sku": "SKU-006", "qty": 220}], new_eta=(promised(db, "SHP-1077") + timedelta(days=10)).isoformat())
    (first,) = listing(client, world["ops_analyst"])
    assert first["type"] == "supplier_delay" and first["warehouse"] == "Mumbai" and first["orders_at_risk"] == 1

    rows = [{"order_ref": f"ORD-61{i}", "customer": cust, "order_date": TODAY.isoformat(),
             "due_date": (TODAY + timedelta(days=due)).isoformat(), "sku": "SKU-006", "warehouse": "Mumbai", "qty": qty}
            for i, (cust, due, qty) in enumerate([("Konkan Fabricators", 4, 40), ("Western Grid Industries", 5, 45),
                                                  ("Thane Hardware Mart", 6, 40), ("Sundaram Auto Parts", 8, 35)], 1)]
    r = client.post("/import/json", headers=auth_headers(world["ops_analyst"]), json={"entity": "orders", "rows": rows})
    assert r.json()["rows_ok"] == 4
    (d,) = listing(client, world["ops_analyst"])
    assert d["id"] == first["id"] and d["type"] == "stock_shortage"  # same disruption, escalated
    assert 4 <= d["orders_at_risk"] <= 6
    assert "cannot cover" in d["summary"]
    updates = [a for a in db.execute(select(AuditLog.action)).scalars() if a == "disruption.updated"]
    assert len(updates) == 1


def test_both_scenarios_together_make_two_disruptions(world, db, client):
    delay_s1(client, db)
    webhook(client, carrier="RoadRunner Freight", shipment_ref="SHP-1077", event_type="partial_delivery",
            received=[{"sku": "SKU-006", "qty": 220}], new_eta=(promised(db, "SHP-1077") + timedelta(days=10)).isoformat())
    assert {d["warehouse"] for d in listing(client, world["ops_analyst"])} == {"Chennai", "Mumbai"}


def test_operator_only_sees_their_own_warehouse(world, db, client):
    delay_s1(client, db)
    webhook(client, carrier="RoadRunner Freight", shipment_ref="SHP-1077", event_type="partial_delivery",
            received=[{"sku": "SKU-006", "qty": 220}], new_eta=(promised(db, "SHP-1077") + timedelta(days=10)).isoformat())
    op = world["warehouse_operator"]  # assigned to Chennai
    seen = listing(client, op)
    assert [d["warehouse"] for d in seen] == ["Chennai"]
    mumbai = next(d for d in listing(client, world["ops_analyst"]) if d["warehouse"] == "Mumbai")
    assert client.get(f"/disruptions/{mumbai['id']}", headers=auth_headers(op)).status_code == 404
    assert client.get(f"/disruptions/{mumbai['id']}/orders", headers=auth_headers(op)).status_code == 404
    assert client.get(f"/disruptions/{seen[0]['id']}", headers=auth_headers(op)).status_code == 200


def test_manual_detect_is_limited_to_analyst_manager_admin(world, db, client):
    for role, code in [("ops_analyst", 200), ("supply_chain_manager", 200), ("administrator", 200),
                       ("warehouse_operator", 403), ("procurement_approver", 403)]:
        assert client.post("/disruptions/detect", headers=auth_headers(world[role])).status_code == code
    assert client.get("/disruptions").status_code == 401


def test_low_stock_without_orders_is_a_low_severity_shortage(world, db, client):
    wh = db.execute(select(Warehouse).where(Warehouse.name == "Delhi")).scalar_one()
    sku = db.execute(select(Sku).where(Sku.code == "SKU-020")).scalar_one()
    inv = db.get(Inventory, (wh.id, sku.id))
    inv.on_hand, inv.safety_stock = 3, 50
    db.flush()
    run_detection(db)
    d = db.execute(select(Disruption).where(Disruption.warehouse_id == wh.id, Disruption.sku_id == sku.id)).scalar_one()
    assert d.type == "stock_shortage" and d.status == "active"


def test_order_risk_rows_are_replaced_not_duplicated(world, db, client):
    delay_s1(client, db)
    delay_s1(client, db, days=9, seq=2, occurred_at=(NOW + timedelta(hours=1)).isoformat())  # slips further
    (d,) = listing(client, world["ops_analyst"])
    rows = db.execute(select(OrderRisk).where(OrderRisk.disruption_id == d["id"])).scalars().all()
    assert len(rows) == d["orders_at_risk"] and len({r.order_id for r in rows}) == len(rows)


def test_every_seed_produces_a_healthy_baseline(db):
    from app.synth.loader import reset_domain_data

    for seed in range(1, 13):
        load_synth(db, generate(seed, TODAY), seed=seed)
        report = run_detection(db)
        assert not report.created, f"seed {seed} starts with a disruption"
        reset_domain_data(db)
