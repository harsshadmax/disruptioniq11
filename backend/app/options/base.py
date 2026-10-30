"""Shared types for the recovery option generators (blueprint 7.5). Everything here is pure.

An option is evaluated by re-running the allocation with the option applied and comparing with the
current allocation, so `orders_saved` is a computed fact and never an estimate.
"""
from dataclasses import dataclass, field
from datetime import date, timedelta

from app.impact.allocation import FULL, Allocation, Demand, Supply, allocate
from app.impact.service import HANDLING_DAYS, CellAnalysis, CellWorld, InboundInfo, LineInfo

# policy constants (documented in the README; change here to tune the prototype)
EXPEDITE_DAYS = 4  # most days a carrier can take off the remaining transit
EXPEDITE_FEE_RATE = 0.06  # expedite fee as a share of the goods' unit cost, per unit
MIN_TRANSIT_DAYS = 1  # nothing arrives sooner than tomorrow
ALT_FIXED_FEE = 5000.0  # onboarding / PO fee for an alternative supplier
SPLIT_FEE = 1500.0  # extra shipment per split order


@dataclass(frozen=True)
class SupplierOffer:
    supplier_id: int
    name: str
    reliability: float
    unit_price: float
    lead_days: int


@dataclass
class OptionContext:
    today: date
    cell: CellWorld
    analysis: CellAnalysis
    sku_code: str
    unit_cost: float
    warehouse_names: dict[int, str]
    sibling_cells: dict[int, CellWorld]  # same SKU in the other warehouses
    transfers: dict[tuple[int, int], tuple[float, int]]  # (from, to) -> (cost per unit, transit days)
    offers: list[SupplierOffer]  # every supplier that can supply this SKU
    trigger: InboundInfo | None  # the shipment behind the disruption, if any

    @property
    def at_risk(self) -> list[LineInfo]:
        return [ln for ln in self.cell.lines if self.analysis.after[ln.line_id].status != FULL]

    @property
    def shortfall(self) -> int:
        return sum(self.analysis.after[ln.line_id].uncovered_qty for ln in self.at_risk)

    @property
    def wh_name(self) -> str:
        return self.warehouse_names[self.cell.warehouse_id]

    def current_supply(self, move: dict[int, date] | None = None) -> list[Supply]:
        """Inbound supply as it stands; `move` re-dates given shipments (by shipment id)."""
        move = move or {}
        return [Supply(move.get(ib.shipment_id, ib.current_eta.date()), ib.qty_expected - ib.qty_received)
                for ib in self.cell.inbound]

    def rerun(self, supply: list[Supply]) -> dict[int, Allocation]:
        demands = [Demand(ln.line_id, ln.due_date, ln.tier, ln.qty) for ln in self.cell.lines]
        return allocate(self.cell.on_hand, supply, demands, self.today, HANDLING_DAYS)


@dataclass
class OptionResult:
    type: str
    feasible: bool
    reasons: list[str]
    params: dict = field(default_factory=dict)
    metrics: dict = field(default_factory=dict)
    steps: list[str] = field(default_factory=list)


def evaluate(ctx: OptionContext, new_alloc: dict[int, Allocation] | None, *, cost: float, new_eta: date | None,
             stock_left: int | None = None, extra_saved: set[int] | None = None) -> dict:
    """Metrics for one option: which at-risk orders it rescues and what that is worth."""
    at_risk = ctx.at_risk
    saved = {ln.line_id for ln in at_risk if new_alloc is not None and new_alloc[ln.line_id].status == FULL}
    saved |= extra_saved or set()
    by_id = {ln.line_id: ln for ln in at_risk}
    penalty_avoided = sum(by_id[i].sla_penalty for i in saved if i in by_id)
    return {
        "orders_saved": len(saved),
        "orders_still_late": len(at_risk) - len(saved),
        "cost": round(cost, 2),
        "penalty_avoided": round(penalty_avoided, 2),
        "net_benefit": round(penalty_avoided - cost, 2),
        "new_eta": new_eta.isoformat() if new_eta else None,
        "stock_left_at_source": stock_left,
        "saved_orders": sorted(by_id[i].order_ref for i in saved if i in by_id),
        "still_late_orders": sorted(ln.order_ref for ln in at_risk if ln.line_id not in saved),
    }


def infeasible(type_: str, reasons: list[str], params: dict | None = None) -> OptionResult:
    metrics = {"orders_saved": 0, "orders_still_late": 0, "cost": 0.0, "penalty_avoided": 0.0, "net_benefit": 0.0,
               "new_eta": None, "stock_left_at_source": None, "saved_orders": [], "still_late_orders": []}
    return OptionResult(type_, False, reasons, params or {}, metrics)


def day(d: date) -> str:
    return f"{d.day} {d.strftime('%b')}"


def plus(d: date, n: int) -> date:
    return d + timedelta(days=n)
