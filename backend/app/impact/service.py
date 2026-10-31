"""Load the current world from the database and run the allocation before (promised) and after (current)."""
from dataclasses import dataclass, field
from datetime import date, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.contracts.rules import max_penalty
from app.contracts.store import confirmed_terms
from app.detect.rules import OPEN_STATUSES
from app.impact.allocation import Allocation, Demand, Supply, allocate, newly_at_risk
from app.models import (
    Customer, Inventory, Order, OrderLine, Shipment, ShipmentLine, Sku, Supplier, Warehouse,
)

HANDLING_DAYS = 1
Cell = tuple[int, int]  # (warehouse_id, sku_id)


@dataclass
class LineInfo:
    line_id: int
    order_id: int
    order_ref: str
    customer: str
    tier: str
    due_date: date
    qty: int  # open quantity on this line
    order_qty: int  # total quantity of the whole order
    sla_penalty: float
    value: float
    allows_partial: bool = False


@dataclass
class InboundInfo:
    shipment_id: int
    ref: str
    supplier_id: int
    supplier: str
    reliability: float
    carrier: str
    status: str
    promised_eta: datetime
    current_eta: datetime
    last_scan_at: datetime | None
    qty_expected: int
    qty_received: int


@dataclass
class CellWorld:
    warehouse_id: int
    sku_id: int
    on_hand: int = 0
    safety_stock: int = 0
    lines: list[LineInfo] = field(default_factory=list)
    inbound: list[InboundInfo] = field(default_factory=list)


@dataclass
class CellAnalysis:
    before: dict[int, Allocation]  # line_id -> allocation if every shipment had arrived as promised
    after: dict[int, Allocation]  # line_id -> allocation with the current ETAs and quantities
    newly_at_risk: set[int]


def load_world(db: Session, only: Cell | None = None) -> dict[Cell, CellWorld]:
    """Every (warehouse, SKU) cell, or just `only` when one cell is wanted (a single disruption's detail page)."""
    world: dict[Cell, CellWorld] = {}

    def cell(wh: int, sku: int) -> CellWorld:
        return world.setdefault((wh, sku), CellWorld(wh, sku))

    inv_q = select(Inventory)
    lines_in_cell = select(OrderLine.order_id)
    lines_q = (select(OrderLine, Order, Customer).join(Order, Order.id == OrderLine.order_id)
               .join(Customer, Customer.id == Order.customer_id).where(Order.status == "open"))
    ships_q = (select(ShipmentLine, Shipment, Supplier).join(Shipment, Shipment.id == ShipmentLine.shipment_id)
               .join(Supplier, Supplier.id == Shipment.supplier_id).where(Shipment.status.in_(OPEN_STATUSES)))
    if only is not None:
        wh_id, sku_id = only
        inv_q = inv_q.where(Inventory.warehouse_id == wh_id, Inventory.sku_id == sku_id)
        lines_in_cell = lines_in_cell.where(OrderLine.warehouse_id == wh_id, OrderLine.sku_id == sku_id)
        lines_q = lines_q.where(OrderLine.warehouse_id == wh_id, OrderLine.sku_id == sku_id)
        ships_q = ships_q.where(Shipment.dest_warehouse_id == wh_id, ShipmentLine.sku_id == sku_id)

    for inv in db.execute(inv_q).scalars():
        c = cell(inv.warehouse_id, inv.sku_id)
        c.on_hand, c.safety_stock = inv.on_hand, inv.safety_stock

    totals_q = select(OrderLine.order_id, func.sum(OrderLine.qty)).group_by(OrderLine.order_id)
    if only is not None:  # the whole order's quantity, but only for the orders that touch this cell
        totals_q = totals_q.where(OrderLine.order_id.in_(lines_in_cell))
    totals = dict(db.execute(totals_q).all())
    rows = db.execute(lines_q).all()
    contracts = confirmed_terms(db)
    for line, order, cust in rows:
        open_qty = line.qty - line.qty_allocated
        if open_qty > 0:
            penalty = float(order.sla_penalty)
            if cust.id in contracts:  # a confirmed contract replaces the order's own penalty
                penalty, _ = max_penalty(contracts[cust.id], float(order.value), penalty)
            cell(line.warehouse_id, line.sku_id).lines.append(LineInfo(
                line.id, order.id, order.ref, cust.name, cust.tier, order.due_date, open_qty, int(totals[order.id]),
                penalty, float(order.value), cust.allows_partial))

    ships = db.execute(ships_q).all()
    for sl, sh, sup in ships:
        cell(sh.dest_warehouse_id, sl.sku_id).inbound.append(InboundInfo(
            sh.id, sh.ref, sup.id, sup.name, sup.reliability_score, sh.carrier, sh.status, sh.promised_eta,
            sh.current_eta, sh.last_scan_at, sl.qty_expected, sl.qty_received))
    return world


def analyze(cell: CellWorld, today: date, handling_days: int = HANDLING_DAYS) -> CellAnalysis:
    demands = [Demand(ln.line_id, ln.due_date, ln.tier, ln.qty) for ln in cell.lines]
    received = sum(ib.qty_received for ib in cell.inbound)
    promised = [Supply(ib.promised_eta.date(), ib.qty_expected) for ib in cell.inbound]
    current = [Supply(ib.current_eta.date(), ib.qty_expected - ib.qty_received) for ib in cell.inbound]
    before = allocate(cell.on_hand - received, promised, demands, today, handling_days)
    after = allocate(cell.on_hand, current, demands, today, handling_days)
    return CellAnalysis(before, after, newly_at_risk(before, after))
