"""What-if simulation (ROADMAP item 1). Read-only: nothing here writes to the database."""
from datetime import date, datetime, timezone
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.deps import require
from app.db import get_db
from app.detect.rules import OPEN_STATUSES
from app.impact.service import load_world
from app.models import Shipment, Sku, Supplier, User, Warehouse
from app.simulate.engine import (
    DemandSurge, Event, Metrics, ShipmentDelay, StockReduction, SupplierShutdown, simulate,
)

router = APIRouter(prefix="/simulate", tags=["simulate"])

NOTE = "Simulation only. Nothing was changed in the real data, and no plan was created."
MAX_EVENTS = 6
TOP_ORDERS = 15


class SupplierShutdownIn(BaseModel):
    kind: Literal["supplier_shutdown"]
    supplier_id: int


class ShipmentDelayIn(BaseModel):
    kind: Literal["shipment_delay"]
    shipment_id: int
    days: int = Field(ge=1, le=90)


class DemandSurgeIn(BaseModel):
    kind: Literal["demand_surge"]
    percent: int = Field(ge=1, le=300)
    warehouse_id: int | None = None
    sku_id: int | None = None


class StockReductionIn(BaseModel):
    kind: Literal["stock_reduction"]
    percent: int = Field(ge=1, le=100)
    warehouse_id: int | None = None
    sku_id: int | None = None


EventIn = Annotated[SupplierShutdownIn | ShipmentDelayIn | DemandSurgeIn | StockReductionIn, Field(discriminator="kind")]


class SimulationIn(BaseModel):
    events: list[EventIn] = Field(min_length=1, max_length=MAX_EVENTS)


class NamedId(BaseModel):
    id: int
    name: str


class SkuOption(BaseModel):
    id: int
    code: str
    name: str


class ShipmentOption(BaseModel):
    id: int
    ref: str
    supplier: str
    warehouse: str
    current_eta: datetime
    status: str


class SimulationOptions(BaseModel):
    suppliers: list[NamedId]
    warehouses: list[NamedId]
    skus: list[SkuOption]
    shipments: list[ShipmentOption]


class MetricsOut(BaseModel):
    orders_at_risk: int
    high_risk_orders: int
    units_short: int
    penalty_exposure: float
    value_at_risk: float
    customers_affected: int
    gold_customers_affected: int


class WarehouseRow(BaseModel):
    warehouse: str
    baseline_orders: int
    simulated_orders: int
    baseline_units_short: int
    simulated_units_short: int
    baseline_penalty: float
    simulated_penalty: float


class OrderRow(BaseModel):
    order_ref: str
    customer: str
    tier: str
    due_date: date
    band: str
    score: float
    uncovered_qty: int
    order_qty: int
    sla_penalty: float
    warehouses: list[str]
    baseline_band: str | None  # None means the order was safe before the scenario


class SimulationOut(BaseModel):
    note: str
    generated_at: datetime
    events: list[str]
    baseline: MetricsOut
    simulated: MetricsOut
    newly_at_risk_orders: int
    by_warehouse: list[WarehouseRow]
    orders: list[OrderRow]


@router.get("/options", response_model=SimulationOptions)
def options(_: User = Depends(require("simulate.run")), db: Session = Depends(get_db)) -> SimulationOptions:
    ships = db.execute(
        select(Shipment, Supplier, Warehouse).join(Supplier, Supplier.id == Shipment.supplier_id)
        .join(Warehouse, Warehouse.id == Shipment.dest_warehouse_id)
        .where(Shipment.status.in_(OPEN_STATUSES)).order_by(Shipment.current_eta, Shipment.id)).all()
    return SimulationOptions(
        suppliers=[NamedId(id=s.id, name=s.name) for s in db.execute(select(Supplier).order_by(Supplier.name)).scalars()],
        warehouses=[NamedId(id=w.id, name=w.name) for w in db.execute(select(Warehouse).order_by(Warehouse.name)).scalars()],
        skus=[SkuOption(id=s.id, code=s.code, name=s.name) for s in db.execute(select(Sku).order_by(Sku.code)).scalars()],
        shipments=[ShipmentOption(id=sh.id, ref=sh.ref, supplier=sup.name, warehouse=wh.name, current_eta=sh.current_eta,
                                  status=sh.status) for sh, sup, wh in ships])


def _metrics_out(m: Metrics) -> MetricsOut:
    return MetricsOut(
        orders_at_risk=m.orders_at_risk, high_risk_orders=m.high_risk_orders, units_short=m.units_short,
        penalty_exposure=round(m.penalty_exposure, 2), value_at_risk=round(m.value_at_risk, 2),
        customers_affected=m.customers_affected, gold_customers_affected=m.gold_customers_affected)


def _scope(db: Session, warehouse_id: int | None, sku_id: int | None) -> str:
    wh = db.get(Warehouse, warehouse_id).name if warehouse_id else "all warehouses"
    sku = db.get(Sku, sku_id).code if sku_id else "all SKUs"
    return f"{sku} at {wh}"


def _to_engine(db: Session, body: SimulationIn, open_ids: set[int]) -> tuple[list[Event], list[str]]:
    """Validate every reference against the database and turn the request into engine events plus plain-English lines."""
    events: list[Event] = []
    lines: list[str] = []

    def bad(msg: str) -> HTTPException:
        return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, msg)

    for ev in body.events:
        if isinstance(ev, SupplierShutdownIn):
            sup = db.get(Supplier, ev.supplier_id)
            if sup is None:
                raise bad(f"Unknown supplier {ev.supplier_id}")
            events.append(SupplierShutdown(sup.id))
            lines.append(f"{sup.name} stops delivering (everything still on the way is lost)")
        elif isinstance(ev, ShipmentDelayIn):
            ship = db.get(Shipment, ev.shipment_id)
            if ship is None or ship.id not in open_ids:
                raise bad(f"Shipment {ev.shipment_id} is not an open shipment")
            events.append(ShipmentDelay(ship.id, ev.days))
            lines.append(f"{ship.ref} arrives {ev.days} day{'s' if ev.days != 1 else ''} later than its current ETA")
        else:
            for ref, model in ((ev.warehouse_id, Warehouse), (ev.sku_id, Sku)):
                if ref is not None and db.get(model, ref) is None:
                    raise bad(f"Unknown {model.__name__.lower()} {ref}")
            scope = _scope(db, ev.warehouse_id, ev.sku_id)
            if isinstance(ev, DemandSurgeIn):
                events.append(DemandSurge(ev.percent, ev.warehouse_id, ev.sku_id))
                lines.append(f"Open order quantity rises {ev.percent}% for {scope}")
            else:
                events.append(StockReduction(ev.percent, ev.warehouse_id, ev.sku_id))
                lines.append(f"On-hand stock falls {ev.percent}% for {scope}")
    return events, lines


@router.post("/run", response_model=SimulationOut)
def run(body: SimulationIn, _: User = Depends(require("simulate.run")), db: Session = Depends(get_db)) -> SimulationOut:
    world = load_world(db)  # plain reads; the engine works on a copy
    open_ids = {ib.shipment_id for cell in world.values() for ib in cell.inbound}
    events, lines = _to_engine(db, body, open_ids)
    now = datetime.now(timezone.utc)
    base, sim = simulate(world, events, now.date())

    names = {w.id: w.name for w in db.execute(select(Warehouse)).scalars()}
    was = {o.order_id: o.band for o in base.orders}
    rows = [
        WarehouseRow(
            warehouse=names[wh],
            baseline_orders=base.by_warehouse.get(wh, {}).get("orders", 0), simulated_orders=sim.by_warehouse.get(wh, {}).get("orders", 0),
            baseline_units_short=base.by_warehouse.get(wh, {}).get("units_short", 0),
            simulated_units_short=sim.by_warehouse.get(wh, {}).get("units_short", 0),
            baseline_penalty=round(base.by_warehouse.get(wh, {}).get("penalty", 0.0), 2),
            simulated_penalty=round(sim.by_warehouse.get(wh, {}).get("penalty", 0.0), 2))
        for wh in sorted(names, key=names.get)]
    orders = [
        OrderRow(order_ref=o.order_ref, customer=o.customer, tier=o.tier, due_date=o.due_date, band=o.band, score=o.score,
                 uncovered_qty=o.uncovered_qty, order_qty=o.order_qty, sla_penalty=o.sla_penalty,
                 warehouses=sorted(names[w] for w in o.warehouse_ids), baseline_band=was.get(o.order_id))
        for o in sim.orders[:TOP_ORDERS]]
    return SimulationOut(
        note=NOTE, generated_at=now, events=lines, baseline=_metrics_out(base), simulated=_metrics_out(sim),
        newly_at_risk_orders=sum(1 for o in sim.orders if o.order_id not in was), by_warehouse=rows, orders=orders)
