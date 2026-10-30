"""Simulated execution of an approved plan (blueprint 7.6). No real system is touched.

`check_preconditions` re-evaluates the plan against the world as it is now. `apply_effects` then moves stock or
dates inside the caller's savepoint, so a failure leaves nothing half-applied.
"""
from datetime import datetime, time, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.detect.rules import OPEN_STATUSES
from app.enums import PlanType
from app.models import Disruption, Inventory, Order, OrderLine, Plan, Shipment, ShipmentLine
from app.options.base import OptionContext
from app.options.generators import overrides_from_params, recompute_option


class ExecutionFailed(Exception):
    pass


def check_preconditions(ctx: OptionContext | None, plan: Plan, d: Disruption) -> list[str]:
    """Reasons the approved plan can no longer be executed as approved (empty list = go)."""
    if d.status != "active" or ctx is None:
        return ["the disruption is no longer active"]
    fresh = recompute_option(ctx, plan.type, **overrides_from_params(plan.type, plan.params_json))
    if not fresh.feasible:
        return ["the plan is no longer feasible: " + "; ".join(fresh.reasons or ["no reason given"])]
    approved, now_saves = plan.metrics_json.get("orders_saved", 0), fresh.metrics["orders_saved"]
    if now_saves < approved:
        return [f"the plan now saves {now_saves} order(s) instead of the {approved} that were approved"]
    return []


def _inventory(db: Session, warehouse_id: int, sku_id: int) -> Inventory | None:
    return db.execute(select(Inventory).where(Inventory.warehouse_id == warehouse_id, Inventory.sku_id == sku_id)
                      .with_for_update().execution_options(populate_existing=True)).scalar_one_or_none()


def _at_ten(iso: str) -> datetime:
    return datetime.combine(datetime.fromisoformat(iso).date(), time(10), tzinfo=timezone.utc)


def apply_effects(db: Session, plan: Plan, d: Disruption) -> dict:
    p, t = plan.params_json, PlanType(plan.type)
    if t == PlanType.REALLOCATE:
        src = _inventory(db, p["source_warehouse_id"], d.sku_id)
        if src is None or src.on_hand - p["qty"] < src.safety_stock:
            raise ExecutionFailed("source warehouse would fall below its safety stock")
        dst = _inventory(db, p["dest_warehouse_id"], d.sku_id)
        src.on_hand -= p["qty"]
        if dst is None:
            db.add(Inventory(warehouse_id=p["dest_warehouse_id"], sku_id=d.sku_id, on_hand=p["qty"], safety_stock=0))
        else:
            dst.on_hand += p["qty"]
        db.flush()
        return {"moved_units": p["qty"], "from": p["source_warehouse"], "to": p["dest_warehouse"]}
    if t == PlanType.EXPEDITE:
        sh = db.execute(select(Shipment).where(Shipment.id == p["shipment_id"]).with_for_update()
                        .execution_options(populate_existing=True)).scalar_one_or_none()
        if sh is None or sh.status not in OPEN_STATUSES:
            raise ExecutionFailed("the shipment is no longer open")
        if sh.current_eta.date().isoformat() != p["current_eta"]:
            raise ExecutionFailed("the shipment ETA changed after approval")
        sh.current_eta = _at_ten(p["new_eta"])
        if sh.status in ("delayed", "in_transit"):
            sh.status = "delayed" if sh.current_eta > sh.promised_eta else "in_transit"
        db.flush()
        return {"shipment": p["shipment_ref"], "new_eta": p["new_eta"]}
    if t == PlanType.ALT_SUPPLIER:
        eta = _at_ten(p["arrival"])
        ship = Shipment(ref=f"SHP-ALT-{plan.id}", supplier_id=p["supplier_id"], carrier="Direct from supplier",
                        dest_warehouse_id=d.warehouse_id, promised_eta=eta, current_eta=eta, status="in_transit",
                        last_seq=0)
        db.add(ship)
        db.flush()
        db.add(ShipmentLine(shipment_id=ship.id, sku_id=d.sku_id, qty_expected=p["qty"]))
        db.flush()
        return {"purchase_order_shipment": ship.ref, "supplier": p["supplier"], "qty": p["qty"], "arrival": p["arrival"]}
    # split: ship the available part now, keep the remainder as open demand
    shipped = 0
    for ln in p["lines"]:
        line = db.execute(
            select(OrderLine).join(Order, Order.id == OrderLine.order_id)
            .where(Order.ref == ln["order_ref"], OrderLine.sku_id == d.sku_id, OrderLine.warehouse_id == d.warehouse_id)
            .with_for_update().execution_options(populate_existing=True)).scalar_one_or_none()
        if line is None or line.qty - line.qty_allocated < ln["ship_now"]:
            raise ExecutionFailed(f"order {ln['order_ref']} no longer has {ln['ship_now']} units open")
        line.qty_allocated += ln["ship_now"]
        shipped += ln["ship_now"]
    inv = _inventory(db, d.warehouse_id, d.sku_id)
    if inv is None or inv.on_hand < shipped:
        raise ExecutionFailed("not enough stock on hand to ship the first parts")
    inv.on_hand -= shipped
    db.flush()
    return {"orders_split": len(p["lines"]), "units_shipped_now": shipped}
