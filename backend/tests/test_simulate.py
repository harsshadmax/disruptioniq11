"""What-if simulation: the pure engine on hand-built worlds, then the API against the synthetic data set."""
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select

from app.enums import Role
from app.impact.service import CellWorld, InboundInfo, LineInfo
from app.models import AuditLog, Disruption, Notification, OrderRisk, Plan, Shipment
from app.simulate.engine import (
    DemandSurge, ShipmentDelay, StockReduction, SupplierShutdown, apply_events, measure, simulate,
)

from tests.conftest import auth_headers
from tests.test_workflow import world  # noqa: F401  (a fixture: synthetic data loaded)

TODAY = date(2026, 6, 1)
NOON = datetime(2026, 6, 1, 12, tzinfo=timezone.utc)


def line(line_id=1, order_id=1, qty=60, due_in=10, tier="silver", penalty=1000.0, order_qty=None, ref=None):
    return LineInfo(line_id, order_id, ref or f"ORD-{order_id}", f"Customer {order_id}", tier, TODAY + timedelta(days=due_in),
                    qty, order_qty or qty, penalty, 5000.0)


def inbound(shipment_id=1, supplier_id=1, qty=100, arrives_in=2, reliability=80.0):
    eta = NOON + timedelta(days=arrives_in)
    return InboundInfo(shipment_id, f"SHP-{shipment_id}", supplier_id, f"Supplier {supplier_id}", reliability, "Carrier",
                       "in_transit", eta, eta, None, qty, 0)


def cell(warehouse=1, sku=1, on_hand=0, lines=(), inbound_=()):
    return CellWorld(warehouse, sku, on_hand, 0, list(lines), list(inbound_))


def one(c: CellWorld) -> dict:
    return {(c.warehouse_id, c.sku_id): c}


def test_a_healthy_world_stays_healthy_under_an_irrelevant_event():
    w = one(cell(lines=[line()], inbound_=[inbound()]))
    base, sim = simulate(w, [ShipmentDelay(shipment_id=99, days=5)], TODAY)
    assert base.orders_at_risk == sim.orders_at_risk == 0


def test_supplier_shutdown_puts_the_orders_the_shipment_fed_at_risk():
    w = one(cell(lines=[line(qty=60)], inbound_=[inbound(supplier_id=7, qty=100)]))
    base, sim = simulate(w, [SupplierShutdown(7)], TODAY)
    assert base.orders_at_risk == 0
    assert sim.orders_at_risk == 1 and sim.units_short == 60 and sim.penalty_exposure == 1000.0
    assert sim.customers_affected == 1


def test_shutdown_keeps_what_was_already_delivered():
    ib = inbound(supplier_id=7, qty=100)
    ib.qty_received = 40  # 40 already counted in on-hand
    w = one(cell(on_hand=40, lines=[line(qty=60)], inbound_=[ib]))
    _, sim = simulate(w, [SupplierShutdown(7)], TODAY)
    assert sim.units_short == 20  # 40 on hand covers 40 of the 60


def test_a_delay_that_runs_past_the_due_date_creates_risk_but_a_short_one_does_not():
    w = one(cell(lines=[line(qty=60, due_in=6)], inbound_=[inbound(shipment_id=3, arrives_in=2)]))
    _, short = simulate(w, [ShipmentDelay(3, 2)], TODAY)  # arrives day 4, order needs it by day 5
    _, long = simulate(w, [ShipmentDelay(3, 5)], TODAY)  # arrives day 7, after the due date
    assert short.orders_at_risk == 0
    assert long.orders_at_risk == 1


def test_demand_surge_grows_the_shortfall_and_the_whole_order_quantity():
    w = one(cell(on_hand=100, lines=[line(qty=80)]))
    base, sim = simulate(w, [DemandSurge(percent=50)], TODAY)
    assert base.orders_at_risk == 0
    assert sim.units_short == 20  # 120 wanted, 100 on hand
    assert sim.orders[0].order_qty == 120


def test_a_surge_grows_each_order_once_even_when_it_spans_two_cells():
    a = cell(warehouse=1, sku=1, on_hand=0, lines=[line(line_id=1, order_id=5, qty=50, order_qty=100)])
    b = cell(warehouse=2, sku=2, on_hand=0, lines=[line(line_id=2, order_id=5, qty=50, order_qty=100)])
    sim = apply_events({(1, 1): a, (2, 2): b}, [DemandSurge(percent=10)])
    assert [ln.qty for c in sim.values() for ln in c.lines] == [55, 55]
    assert [ln.order_qty for c in sim.values() for ln in c.lines] == [110, 110]


def test_stock_reduction_cuts_what_is_on_hand():
    w = one(cell(on_hand=100, lines=[line(qty=80)]))
    _, sim = simulate(w, [StockReduction(percent=50)], TODAY)
    assert sim.units_short == 30


def test_scope_limits_an_event_to_its_warehouse_and_sku():
    w = {(1, 1): cell(1, 1, on_hand=100, lines=[line(1, 1, qty=80)]), (2, 1): cell(2, 1, on_hand=100, lines=[line(2, 2, qty=80)])}
    _, sim = simulate(w, [StockReduction(percent=50, warehouse_id=2)], TODAY)
    assert [o.order_id for o in sim.orders] == [2]
    _, other_sku = simulate(w, [StockReduction(percent=50, sku_id=9)], TODAY)
    assert other_sku.orders_at_risk == 0


def test_several_events_combine():
    w = one(cell(on_hand=50, lines=[line(qty=60, due_in=8)], inbound_=[inbound(shipment_id=4, supplier_id=2, qty=40, arrives_in=2)]))
    base, _ = simulate(w, [], TODAY)
    _, delay_only = simulate(w, [ShipmentDelay(4, 7)], TODAY)  # arrives after the due date, so only the 50 on hand counts
    _, cut_only = simulate(w, [StockReduction(percent=50)], TODAY)  # 25 on hand + 40 arriving in time = 65, still enough
    _, both = simulate(w, [ShipmentDelay(4, 7), StockReduction(percent=50)], TODAY)  # only 25 on hand counts
    assert base.orders_at_risk == 0 and cut_only.orders_at_risk == 0
    assert delay_only.units_short == 10 and both.units_short == 35


def test_the_original_world_is_never_modified():
    w = one(cell(on_hand=100, lines=[line(qty=80)], inbound_=[inbound()]))
    before = deepcopy(w)
    simulate(w, [SupplierShutdown(1), ShipmentDelay(1, 9), DemandSurge(80), StockReduction(90)], TODAY)
    assert w == before


def test_an_order_with_lines_in_two_cells_counts_once_and_its_risk_is_its_worst_line():
    a = cell(1, 1, on_hand=0, lines=[line(line_id=1, order_id=8, qty=50, order_qty=100)])
    b = cell(2, 2, on_hand=0, lines=[line(line_id=2, order_id=8, qty=50, order_qty=100)])
    m = measure({(1, 1): a, (2, 2): b}, TODAY)
    assert m.orders_at_risk == 1 and m.penalty_exposure == 1000.0 and m.units_short == 100
    assert m.by_warehouse[1]["orders"] == 1 and m.by_warehouse[2]["orders"] == 1


# ---- API ----------------------------------------------------------------------------------------------------------

def user_of(users, role):
    return users[role.value]


def counts(db):
    return [db.execute(select(func.count()).select_from(t)).scalar_one() for t in (Disruption, Plan, OrderRisk, Notification, AuditLog)]


def eta_of(db, ref):
    return db.execute(select(Shipment.current_eta).where(Shipment.ref == ref)).scalar_one()


def get_options(client, user):
    resp = client.get("/simulate/options", headers=auth_headers(user))
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_options_list_what_can_be_simulated(world, client):
    opts = get_options(client, user_of(world, Role.ANALYST))
    assert {"SHP-1042", "SHP-1077"} <= {s["ref"] for s in opts["shipments"]}
    assert "Coastal Polymers" in {s["name"] for s in opts["suppliers"]}
    assert opts["warehouses"] and opts["skus"]


def test_a_simulation_writes_nothing(world, db, client):
    analyst = user_of(world, Role.ANALYST)
    opts = get_options(client, analyst)
    sup = next(s for s in opts["suppliers"] if s["name"] == "Coastal Polymers")
    before, eta = counts(db), eta_of(db, "SHP-1042")
    resp = client.post("/simulate/run", headers=auth_headers(analyst), json={"events": [
        {"kind": "supplier_shutdown", "supplier_id": sup["id"]}, {"kind": "demand_surge", "percent": 40}]})
    assert resp.status_code == 200, resp.text
    assert counts(db) == before and eta_of(db, "SHP-1042") == eta
    body = resp.json()
    assert "Nothing was changed" in body["note"] and len(body["events"]) == 2
    assert body["simulated"]["orders_at_risk"] >= body["baseline"]["orders_at_risk"]


def test_a_supplier_shutdown_creates_risk_that_the_baseline_did_not_have(world, client):
    analyst = user_of(world, Role.ANALYST)
    opts = get_options(client, analyst)
    sup = next(s for s in opts["suppliers"] if s["name"] == "Coastal Polymers")
    body = client.post("/simulate/run", headers=auth_headers(analyst),
                       json={"events": [{"kind": "supplier_shutdown", "supplier_id": sup["id"]}]}).json()
    assert body["baseline"]["orders_at_risk"] == 0
    assert body["simulated"]["orders_at_risk"] > 0 and body["newly_at_risk_orders"] == body["simulated"]["orders_at_risk"]
    assert body["orders"] and all(o["baseline_band"] is None for o in body["orders"])
    assert any(r["simulated_orders"] > 0 for r in body["by_warehouse"])


def test_the_baseline_matches_what_detection_has_flagged(world, db, client):
    from app.detect.service import run_detection

    analyst = user_of(world, Role.ANALYST)
    ship = next(s for s in get_options(client, analyst)["shipments"] if s["ref"] == "SHP-1042")
    db.execute(Shipment.__table__.update().where(Shipment.ref == "SHP-1042").values(
        current_eta=eta_of(db, "SHP-1042") + timedelta(days=6)))
    run_detection(db)
    flagged = db.execute(select(func.count(func.distinct(OrderRisk.order_id)))).scalar_one()
    assert flagged > 0
    body = client.post("/simulate/run", headers=auth_headers(analyst),
                       json={"events": [{"kind": "shipment_delay", "shipment_id": ship["id"], "days": 1}]}).json()
    assert body["baseline"]["orders_at_risk"] == flagged


@pytest.mark.parametrize("events", [
    [], [{"kind": "supplier_shutdown", "supplier_id": 999999}],
    [{"kind": "shipment_delay", "shipment_id": 999999, "days": 3}],
    [{"kind": "shipment_delay", "shipment_id": 1, "days": 0}],
    [{"kind": "demand_surge", "percent": 0}], [{"kind": "stock_reduction", "percent": 101}],
    [{"kind": "demand_surge", "percent": 10, "warehouse_id": 999999}],
    [{"kind": "mystery"}], [{"kind": "demand_surge", "percent": 5}] * 7,
])
def test_bad_scenarios_are_rejected(world, client, events):
    resp = client.post("/simulate/run", headers=auth_headers(user_of(world, Role.ANALYST)), json={"events": events})
    assert resp.status_code == 422


@pytest.mark.parametrize("role,expected", [
    (Role.ANALYST, 200), (Role.MANAGER, 200), (Role.PROCUREMENT, 200), (Role.ADMIN, 200), (Role.OPERATOR, 403)])
def test_who_may_simulate(world, client, role, expected):
    resp = client.get("/simulate/options", headers=auth_headers(user_of(world, role)))
    assert resp.status_code == expected
