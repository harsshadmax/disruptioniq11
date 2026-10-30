"""What-if simulation. Pure: no database, no clock, and the world it is given is never modified.

A scenario is a list of events applied to a copy of the current world (blueprint 7.2 allocation, 7.3 risk).
The same allocation and risk rules that detection uses are run on the copy, so baseline and simulated numbers
are directly comparable and every figure can be explained by the existing rules.
"""
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import date, timedelta

from app.decide.risk import risk_score
from app.impact.allocation import FULL
from app.impact.service import CellWorld, analyze

World = dict[tuple[int, int], CellWorld]


@dataclass(frozen=True)
class SupplierShutdown:
    supplier_id: int  # every open shipment from this supplier stops delivering what it has not yet delivered


@dataclass(frozen=True)
class ShipmentDelay:
    shipment_id: int
    days: int  # added to the shipment's current ETA


@dataclass(frozen=True)
class DemandSurge:
    percent: int  # open order quantity grows by this percentage (rounded up)
    warehouse_id: int | None = None  # None means every warehouse
    sku_id: int | None = None  # None means every SKU


@dataclass(frozen=True)
class StockReduction:
    percent: int  # on-hand stock shrinks by this percentage (rounded down)
    warehouse_id: int | None = None
    sku_id: int | None = None


Event = SupplierShutdown | ShipmentDelay | DemandSurge | StockReduction


@dataclass
class OrderImpact:
    order_id: int
    order_ref: str
    customer: str
    tier: str
    due_date: date
    score: float
    band: str
    uncovered_qty: int
    order_qty: int
    sla_penalty: float
    value: float
    warehouse_ids: set[int] = field(default_factory=set)


@dataclass
class Metrics:
    orders_at_risk: int
    high_risk_orders: int
    units_short: int
    penalty_exposure: float  # sum of the SLA penalty of each at-risk order, counted once
    value_at_risk: float  # sum of the value of each at-risk order, counted once
    customers_affected: int
    gold_customers_affected: int
    by_warehouse: dict[int, dict]  # warehouse_id -> {orders, units_short, penalty}
    orders: list[OrderImpact]  # worst first


def _matches(cell: CellWorld, warehouse_id: int | None, sku_id: int | None) -> bool:
    return (warehouse_id is None or cell.warehouse_id == warehouse_id) and (sku_id is None or cell.sku_id == sku_id)


def apply_events(world: World, events: list[Event]) -> World:
    """A modified deep copy of `world`. The original is left exactly as it was."""
    sim = deepcopy(world)
    for ev in events:
        if isinstance(ev, SupplierShutdown):
            for cell in sim.values():
                for ib in cell.inbound:
                    if ib.supplier_id == ev.supplier_id:
                        ib.qty_expected = ib.qty_received  # nothing more will arrive
        elif isinstance(ev, ShipmentDelay):
            for cell in sim.values():
                for ib in cell.inbound:
                    if ib.shipment_id == ev.shipment_id:
                        ib.current_eta = ib.current_eta + timedelta(days=ev.days)
        elif isinstance(ev, DemandSurge):
            added: dict[int, int] = {}
            for cell in sim.values():
                if not _matches(cell, ev.warehouse_id, ev.sku_id):
                    continue
                for ln in cell.lines:
                    grown = -(-ln.qty * (100 + ev.percent) // 100)  # integer ceiling: float 50 * 1.1 would round up to 56
                    added[ln.order_id] = added.get(ln.order_id, 0) + grown - ln.qty
                    ln.qty = grown
            for cell in sim.values():  # the risk score compares the shortfall with the whole order
                for ln in cell.lines:
                    ln.order_qty += added.get(ln.order_id, 0)
        elif isinstance(ev, StockReduction):
            for cell in sim.values():
                if _matches(cell, ev.warehouse_id, ev.sku_id):
                    cell.on_hand = max(cell.on_hand, 0) * (100 - ev.percent) // 100
    return sim


def measure(world: World, today: date) -> Metrics:
    """Run the allocation on the current ETAs and score every order that is not fully covered."""
    orders: dict[int, OrderImpact] = {}
    short_by_wh: dict[int, int] = {}
    for cell in world.values():
        if not cell.lines:
            continue
        after = analyze(cell, today).after
        short = sum(al.uncovered_qty for al in after.values())
        if short:
            short_by_wh[cell.warehouse_id] = short_by_wh.get(cell.warehouse_id, 0) + short
        reliabilities = [ib.reliability for ib in cell.inbound]
        reliability = min(reliabilities) if reliabilities else None  # same "worst feeding supplier" view as detection
        for ln in cell.lines:
            al = after[ln.line_id]
            if al.status == FULL:
                continue
            r = risk_score(uncovered_qty=al.uncovered_qty, order_qty=ln.order_qty, slack_days=al.slack_days,
                           tier=ln.tier, sla_penalty=ln.sla_penalty, supplier_reliability=reliability)
            row = orders.get(ln.order_id)
            if row is None:
                row = orders[ln.order_id] = OrderImpact(
                    ln.order_id, ln.order_ref, ln.customer, ln.tier, ln.due_date, r.score, r.band, 0, ln.order_qty,
                    ln.sla_penalty, ln.value)
            row.uncovered_qty += al.uncovered_qty
            row.warehouse_ids.add(cell.warehouse_id)
            row.due_date = min(row.due_date, ln.due_date)
            if r.score > row.score:  # an order is as risky as its riskiest line
                row.score, row.band = r.score, r.band

    ranked = sorted(orders.values(), key=lambda o: (-o.score, o.due_date, o.order_id))
    by_wh: dict[int, dict] = {wh: {"orders": 0, "units_short": short, "penalty": 0.0} for wh, short in short_by_wh.items()}
    for o in ranked:  # an order with lines in two warehouses counts once in each
        for wh in o.warehouse_ids:
            slot = by_wh.setdefault(wh, {"orders": 0, "units_short": 0, "penalty": 0.0})
            slot["orders"] += 1
            slot["penalty"] += o.sla_penalty

    customers = {o.customer for o in ranked}
    gold = {o.customer for o in ranked if o.tier == "gold"}
    return Metrics(
        orders_at_risk=len(ranked), high_risk_orders=sum(1 for o in ranked if o.band == "high"),
        units_short=sum(o.uncovered_qty for o in ranked), penalty_exposure=sum(o.sla_penalty for o in ranked),
        value_at_risk=sum(o.value for o in ranked), customers_affected=len(customers),
        gold_customers_affected=len(gold), by_warehouse=by_wh, orders=ranked)


def simulate(world: World, events: list[Event], today: date) -> tuple[Metrics, Metrics]:
    """(baseline, simulated). Baseline is the world as it stands today."""
    return measure(world, today), measure(apply_events(world, events), today)
