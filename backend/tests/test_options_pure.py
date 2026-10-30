"""Recovery option generators on hand-built Scenario 1 / 2 worlds (no database)."""
from datetime import date, datetime, time, timedelta, timezone

import pytest

from app.impact.service import CellWorld, InboundInfo, LineInfo, analyze
from app.options.base import ALT_FIXED_FEE, EXPEDITE_DAYS, SPLIT_FEE, OptionContext, SupplierOffer
from app.options.generators import alt_supplier, expedite, generate_options, reallocate, split_orders

TODAY = date(2026, 11, 2)
CHENNAI, BENGALURU, MUMBAI, DELHI = 1, 2, 3, 4
NAMES = {CHENNAI: "Chennai", BENGALURU: "Bengaluru", MUMBAI: "Mumbai", DELHI: "Delhi"}
LANES = {(BENGALURU, CHENNAI): (4.0, 1), (MUMBAI, CHENNAI): (9.0, 3), (DELHI, CHENNAI): (14.0, 4),
         (DELHI, MUMBAI): (8.0, 2), (BENGALURU, MUMBAI): (7.0, 2), (CHENNAI, MUMBAI): (9.0, 3)}


def at(offset: int) -> datetime:
    return datetime.combine(TODAY + timedelta(days=offset), time(10), tzinfo=timezone.utc)


def line(i, ref, tier, due, qty, penalty, partial=False):
    return LineInfo(i, i, ref, f"Customer {i}", tier, TODAY + timedelta(days=due), qty, qty, penalty, penalty * 5, partial)


def shipment(qty, promised, current, received=0, status="delayed", supplier=1):
    return InboundInfo(10, "SHP-1042", supplier, "Coastal Polymers", 74.0, "SeaLink Logistics", status,
                       at(promised), at(current), None, qty, received)


def s1_ctx(*, bengaluru_on_hand=600, partial_flags=False, offers=None, current_eta=9) -> OptionContext:
    lines = [line(i, f"ORD-500{i}", t, d, q, p, partial_flags) for i, (t, d, q, p) in enumerate(
        [("gold", 4, 45, 40000), ("silver", 5, 30, 20000), ("bronze", 6, 25, 5000), ("gold", 7, 35, 60000),
         ("silver", 8, 30, 10000), ("bronze", 9, 20, 2000), ("gold", 12, 50, 25000)], start=1)]
    ship = shipment(260, 3, current_eta)
    cell = CellWorld(CHENNAI, 7, on_hand=40, safety_stock=20, lines=lines, inbound=[ship])
    siblings = {
        BENGALURU: CellWorld(BENGALURU, 7, on_hand=bengaluru_on_hand, safety_stock=20),
        MUMBAI: CellWorld(MUMBAI, 7, on_hand=60, safety_stock=30, lines=[line(90, "ORD-X", "bronze", 9, 40, 0)]),
        DELHI: CellWorld(DELHI, 7, on_hand=15, safety_stock=20),
    }
    offers = offers if offers is not None else [
        SupplierOffer(1, "Coastal Polymers", 74.0, 1702.0, 9), SupplierOffer(6, "Deccan Plastics", 85.0, 1990.0, 6),
        SupplierOffer(3, "Slow Traders", 90.0, 1800.0, 12)]
    return OptionContext(TODAY, cell, analyze(cell, TODAY), "SKU-001", 1850.0, NAMES, siblings, LANES, offers, ship)


def test_the_world_is_actually_in_trouble():
    ctx = s1_ctx()
    assert len(ctx.at_risk) == 6 and ctx.shortfall == 145


def test_reallocate_pulls_the_shortfall_from_the_warehouse_with_surplus():
    r = reallocate(s1_ctx())
    assert r.feasible and r.params["source_warehouse"] == "Bengaluru" and r.params["qty"] == 145
    m = r.metrics
    assert m["orders_saved"] == 6 and m["orders_still_late"] == 0
    assert m["cost"] == pytest.approx(145 * 4.0) and m["stock_left_at_source"] == 600 - 145
    assert m["penalty_avoided"] == pytest.approx(40000 + 20000 + 5000 + 60000 + 10000 + 2000)
    assert m["net_benefit"] == pytest.approx(m["penalty_avoided"] - m["cost"]) and m["new_eta"] == "2026-11-03"
    others = {c["warehouse"]: c for c in r.params["considered"]}
    assert not others["Mumbai"]["feasible"] and "no surplus" in others["Mumbai"]["reason"]
    assert not others["Delhi"]["feasible"] and others["Bengaluru"]["feasible"]
    assert len(r.steps) >= 3


def test_reallocate_reports_why_when_nobody_has_surplus():
    r = reallocate(s1_ctx(bengaluru_on_hand=20))
    assert not r.feasible and r.metrics["orders_saved"] == 0
    assert len(r.reasons) == 3 and all("no surplus" in x for x in r.reasons)


def test_reallocate_partial_surplus_saves_fewer_orders_and_says_so():
    r = reallocate(s1_ctx(bengaluru_on_hand=120))  # surplus 100 of the 145 short
    assert r.feasible and r.params["qty"] == 100 and "Only 100 of the 145" in r.reasons[0]
    assert 0 < r.metrics["orders_saved"] < 6


def test_expedite_pulls_the_eta_forward_and_saves_some_orders():
    r = expedite(s1_ctx())
    assert r.feasible and r.params["days_saved"] == EXPEDITE_DAYS and r.params["new_eta"] == "2026-11-07"
    m = r.metrics
    assert 0 < m["orders_saved"] < 6 and m["cost"] == pytest.approx(260 * 1850 * 0.06)
    assert m["new_eta"] == "2026-11-07" and m["stock_left_at_source"] is None


def test_expedite_is_infeasible_when_the_shipment_cannot_come_sooner():
    ctx = s1_ctx()
    ctx.cell.inbound[0] = ctx.trigger = shipment(50, 1, 1, status="in_transit")  # due tomorrow, orders still short
    ctx.analysis = analyze(ctx.cell, TODAY)
    r = expedite(ctx)
    assert ctx.at_risk and not r.feasible and "already due" in r.reasons[0]


def test_expedite_without_any_inbound_shipment():
    ctx = s1_ctx()
    ctx.cell.inbound.clear()
    ctx.trigger = None
    assert expedite(ctx).reasons == ["No inbound shipment is open for this SKU at this warehouse"]


def test_alt_supplier_picks_a_supplier_that_beats_the_delayed_eta():
    r = alt_supplier(s1_ctx())
    assert r.feasible and r.params["supplier"] == "Deccan Plastics" and r.params["qty"] == 145
    m = r.metrics
    assert m["cost"] == pytest.approx(145 * (1990 - 1702) + ALT_FIXED_FEE) and m["orders_saved"] >= 1
    rejected = {c["supplier"]: c for c in r.params["considered"]}
    assert "Coastal Polymers" not in rejected  # the delayed supplier is not its own alternative
    assert not rejected["Slow Traders"]["feasible"] and "not before the delayed ETA" in rejected["Slow Traders"]["reason"]


def test_alt_supplier_infeasible_when_nobody_is_faster():
    ctx = s1_ctx(offers=[SupplierOffer(1, "Coastal Polymers", 74.0, 1702.0, 9), SupplierOffer(3, "Slow Traders", 90.0, 1800.0, 12)])
    r = alt_supplier(ctx)
    assert not r.feasible and "Slow Traders" in r.reasons[0]


def test_alt_supplier_prefers_the_more_reliable_one():
    offers = [SupplierOffer(1, "Coastal Polymers", 74.0, 1702.0, 9), SupplierOffer(6, "Cheap But Flaky", 60.0, 1710.0, 5),
              SupplierOffer(7, "Solid Supply", 95.0, 2100.0, 5)]
    assert alt_supplier(s1_ctx(offers=offers)).params["supplier"] == "Solid Supply"


def test_split_is_infeasible_when_customers_refuse_partial_shipments():
    r = split_orders(s1_ctx())
    assert not r.feasible and r.metrics["orders_saved"] == 0
    assert any("does not accept partial shipments" in x for x in r.reasons)


def test_split_ships_what_is_available_for_customers_who_agree():
    r = split_orders(s1_ctx(partial_flags=True))
    assert r.feasible and len(r.params["lines"]) == 1  # only the partly covered order has stock to ship now
    only = r.params["lines"][0]
    assert only["order_ref"] == "ORD-5001" and only["ship_now"] == 40 and only["remainder"] == 5
    assert r.metrics["orders_saved"] == 1 and r.metrics["cost"] == SPLIT_FEE
    assert any("no stock available now" in x for x in r.reasons)


def test_generate_options_returns_all_four_with_feasible_ones_first():
    results = generate_options(s1_ctx())
    assert {r.type for r in results} == {"reallocate", "expedite", "alt_supplier", "split"}
    flags = [r.feasible for r in results]
    assert flags == sorted(flags, reverse=True)
    feasible = [r for r in results if r.feasible]
    assert [r.metrics["net_benefit"] for r in feasible] == sorted((r.metrics["net_benefit"] for r in feasible), reverse=True)
    assert feasible[0].type == "reallocate"  # cheapest way to save all 6


def test_s1_has_options_that_differ_in_cost_and_orders_saved():
    feasible = [r for r in generate_options(s1_ctx()) if r.feasible]
    assert len(feasible) >= 3 and len({(r.metrics["cost"], r.metrics["orders_saved"]) for r in feasible}) >= 3


def test_nothing_at_risk_means_nothing_to_recover():
    ctx = s1_ctx(current_eta=3)
    assert all(not r.feasible and "nothing to recover" in r.reasons[0] for r in generate_options(ctx))
