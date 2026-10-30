"""Pure-function tests for allocation, risk score and detection rules (no database)."""
from datetime import date, datetime, timedelta, timezone

import pytest

from app.decide.risk import band_for, risk_score, time_risk
from app.detect.rules import below_safety_stock, delay_days, late_shipment_reasons, supplier_delay_reasons
from app.impact.allocation import FULL, NONE, PARTIAL, Demand, Supply, allocate, newly_at_risk

TODAY = date(2026, 11, 2)
D = lambda day: date(2026, 11, day)  # noqa: E731


def test_everything_on_hand_is_covered_in_due_date_order():
    out = allocate(100, [], [Demand(1, D(10), "bronze", 40), Demand(2, D(5), "bronze", 40)], TODAY)
    assert out[1].status == out[2].status == FULL and out[2].earliest_fulfil == D(3)  # today + 1 handling day


def test_earliest_due_date_gets_the_stock_first_and_the_late_one_is_short():
    out = allocate(50, [], [Demand(1, D(10), "gold", 40), Demand(2, D(5), "bronze", 40)], TODAY)
    assert out[2].status == FULL
    assert out[1].status == PARTIAL and out[1].covered_qty == 10 and out[1].uncovered_qty == 30
    assert out[1].earliest_fulfil is None and out[1].slack_days is None


def test_tier_breaks_ties_on_the_same_due_date():
    out = allocate(30, [], [Demand(1, D(8), "bronze", 30), Demand(2, D(8), "gold", 30)], TODAY)
    assert out[2].status == FULL and out[1].status == NONE


def test_inbound_counts_only_from_its_arrival_day_minus_handling():
    supply = [Supply(D(6), 50)]
    ok = allocate(0, supply, [Demand(1, D(7), "silver", 50)], TODAY)  # arrives 6th, handled 6th, due 7th
    late = allocate(0, supply, [Demand(1, D(6), "silver", 50)], TODAY)
    assert ok[1].status == FULL and ok[1].earliest_fulfil == D(7) and ok[1].slack_days == 0
    assert late[1].status == NONE and late[1].earliest_fulfil == D(7) and late[1].slack_days == -1


def test_an_order_already_past_due_is_never_covered():
    out = allocate(500, [], [Demand(1, D(1), "gold", 5)], TODAY)
    assert out[1].status == NONE


def test_past_arrival_dates_count_as_on_hand_today():
    out = allocate(0, [Supply(D(1), 20)], [Demand(1, D(5), "bronze", 20)], TODAY)
    assert out[1].status == FULL and out[1].earliest_fulfil == D(3)


# --- Scenario 1: SHP-1042 slips from the 5th to the 11th; 40 on hand, 260 inbound -----------------------------
S1_DEMAND = [Demand(i, D(2 + due), t, q) for i, (due, t, q) in enumerate(
    [(4, "gold", 45), (5, "silver", 30), (6, "bronze", 25), (7, "gold", 35), (8, "silver", 30), (9, "bronze", 20),
     (12, "gold", 50)], start=1)]


def test_scenario_1_six_of_seven_orders_become_newly_at_risk():
    before = allocate(40, [Supply(D(5), 260)], S1_DEMAND, TODAY)
    after = allocate(40, [Supply(D(11), 260)], S1_DEMAND, TODAY)
    assert all(a.status == FULL for a in before.values())
    assert after[1].status == PARTIAL and after[1].covered_qty == 40
    assert [after[i].status for i in range(2, 7)] == [NONE] * 5
    assert after[7].status == FULL  # due on the 14th, stock lands on the 11th
    assert newly_at_risk(before, after) == {1, 2, 3, 4, 5, 6}


# --- Scenario 2: Metro Components delivers 220 of 400, then 4 more orders arrive ---------------------------------
S2_DEMAND = [Demand(i, D(2 + due), t, q) for i, (due, t, q) in enumerate(
    [(3, "gold", 60), (5, "silver", 70), (7, "bronze", 80), (9, "gold", 70), (11, "silver", 60),   # original book
     (4, "silver", 40), (5, "gold", 45), (6, "bronze", 40), (8, "gold", 35)], start=1)]               # burst


def test_scenario_2_shortage_exists_even_under_the_promise_and_is_worse_now():
    promised = allocate(60, [Supply(D(4), 400)], S2_DEMAND, TODAY)   # nothing delivered yet, full PO promised
    now = allocate(280, [Supply(D(14), 180)], S2_DEMAND, TODAY)      # 220 received, balance pushed to the 14th
    uncovered_promised = {k for k, a in promised.items() if a.status != FULL}
    uncovered_now = {k for k, a in now.items() if a.status != FULL}
    assert uncovered_promised == {5}                       # demand 500 > promised supply 460
    assert len(uncovered_now) == 4                         # 4 to 6 orders at risk, as in the blueprint
    assert uncovered_promised <= uncovered_now


# --- risk score ------------------------------------------------------------------------------------------------------
def test_time_risk_tiers():
    assert [time_risk(s) for s in (None, -3, 0, 1, 2, 3, 10)] == [1.0, 1.0, 1.0, 0.6, 0.6, 0.2, 0.2]


def test_bands():
    assert (band_for(59.9), band_for(60), band_for(29.9), band_for(30)) == ("medium", "high", "low", "medium")


def test_risk_score_matches_the_formula_and_the_factors_add_up():
    r = risk_score(uncovered_qty=45, order_qty=45, slack_days=-2, tier="gold", sla_penalty=60000,
                   supplier_reliability=74)
    assert r.score == pytest.approx(30 + 25 + 20 + 15 + 2.6, abs=0.05) and r.band == "high"
    assert sum(f["points"] for f in r.factors) == pytest.approx(r.score, abs=0.05)
    assert {f["name"] for f in r.factors} == {"shortfall", "time", "tier", "penalty", "supplier"}
    assert next(f for f in r.factors if f["name"] == "tier")["text"] == "Gold customer"


def test_risk_score_bronze_small_shortfall_is_lower_than_gold_full_shortfall():
    gold = risk_score(uncovered_qty=50, order_qty=50, slack_days=0, tier="gold", sla_penalty=40000, supplier_reliability=80)
    bronze = risk_score(uncovered_qty=5, order_qty=50, slack_days=0, tier="bronze", sla_penalty=0, supplier_reliability=80)
    assert gold.score > bronze.score and gold.band == "high" and bronze.band in ("low", "medium")


def test_risk_score_handles_degenerate_inputs():
    r = risk_score(uncovered_qty=5, order_qty=0, slack_days=None, tier="unknown", sla_penalty=-5, supplier_reliability=None)
    assert 0 <= r.score <= 100
    big = risk_score(uncovered_qty=999, order_qty=1, slack_days=0, tier="gold", sla_penalty=1e9, supplier_reliability=-50)
    assert big.score <= 100


# --- detection rules -------------------------------------------------------------------------------------------------
NOW = datetime(2026, 11, 2, 12, tzinfo=timezone.utc)
PROMISED = datetime(2026, 11, 5, 10, tzinfo=timezone.utc)


def late(**over):
    base = dict(status="in_transit", promised_eta=PROMISED, current_eta=PROMISED, last_scan_at=None, now=NOW)
    base.update(over)
    return late_shipment_reasons(**base)


def test_on_time_shipment_is_not_late():
    assert late() == [] and late(last_scan_at=NOW - timedelta(hours=5)) == []


def test_eta_slip_status_and_scan_gap_each_make_a_shipment_late():
    assert "6 day(s)" in late(current_eta=PROMISED + timedelta(days=6))[0]
    assert late(status="delayed") == ["carrier reports the shipment as delayed"]
    assert "no carrier scan" in late(last_scan_at=NOW - timedelta(hours=37))[0]
    assert late(last_scan_at=NOW - timedelta(hours=35)) == []  # 3 x 12h = 36h is the limit
    assert late(status="delivered", current_eta=PROMISED + timedelta(days=9)) == []


def test_earlier_eta_is_not_a_delay():
    assert late(current_eta=PROMISED - timedelta(days=1)) == [] and delay_days(PROMISED, PROMISED - timedelta(days=1)) == 0


def test_supplier_delay_rules():
    assert supplier_delay_reasons(partial_receipt=False, late_open_shipments=1) == []
    assert supplier_delay_reasons(partial_receipt=True, late_open_shipments=0)
    assert supplier_delay_reasons(partial_receipt=False, late_open_shipments=2)
    assert supplier_delay_reasons(partial_receipt=False, late_open_shipments=0, recent_lead_times=[10, 11, 12],
                                  baseline_lead_days=8)
    assert supplier_delay_reasons(partial_receipt=False, late_open_shipments=0, recent_lead_times=[9, 10, 9],
                                  baseline_lead_days=8) == []
    assert supplier_delay_reasons(partial_receipt=False, late_open_shipments=0, recent_lead_times=[20],
                                  baseline_lead_days=8) == []  # not enough history to judge


def test_below_safety_stock():
    assert below_safety_stock(on_hand=40, inbound=260, demand=235, safety_stock=40) is False
    assert below_safety_stock(on_hand=40, inbound=0, demand=235, safety_stock=40) is True
