"""Write generated synthetic data to the database (natural keys -> ids)."""
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.audit.service import write_audit
from app.models import (
    Customer, CustomerContract, Disruption, ImportBatch, ImportRowError, Inventory, Notification, Order, OrderLine, OrderRisk, Plan,
    PlanStep, Shipment, ShipmentEvent, ShipmentLine, Sku, Supplier, SupplierItem, TransferCost, Warehouse,
)


class SynthAlreadyLoaded(RuntimeError):
    pass


# children before parents; users, warehouses and the audit log are never touched
_RESET_ORDER = [
    CustomerContract, Notification, PlanStep, Plan, OrderRisk, Disruption, ImportRowError, ImportBatch, ShipmentEvent, ShipmentLine,
    Shipment, OrderLine, Order, Customer, TransferCost, Inventory, SupplierItem, Sku, Supplier,
]


def reset_domain_data(db: Session) -> None:
    for model in _RESET_ORDER:
        db.execute(delete(model))
    db.flush()


def load_synth(db: Session, data: dict[str, list[dict]], *, seed: int | None = None, actor_id: int | None = None,
               role: str | None = None) -> dict[str, int]:
    if db.execute(select(func.count(Sku.id))).scalar_one() > 0:
        raise SynthAlreadyLoaded("Domain data already present; reset first (python -m app.synth --reset)")

    wh: dict[str, int] = {}
    for w in data["warehouses"]:  # warehouses may already exist because users reference them
        row = db.execute(select(Warehouse).where(Warehouse.name == w["name"])).scalar_one_or_none()
        if row is None:
            row = Warehouse(**w)
            db.add(row)
            db.flush()
        wh[w["name"]] = row.id

    def add_all(model, rows):
        objs = [model(**r) for r in rows]
        db.add_all(objs)
        db.flush()
        return objs

    sup = {s.name: s.id for s in add_all(Supplier, data["suppliers"])}
    sku = {s.code: s.id for s in add_all(Sku, data["skus"])}
    add_all(SupplierItem, [{"supplier_id": sup[r["supplier"]], "sku_id": sku[r["sku"]], "unit_price": r["unit_price"],
                            "lead_days": r["lead_days"]} for r in data["supplier_items"]])
    add_all(Inventory, [{"warehouse_id": wh[r["warehouse"]], "sku_id": sku[r["sku"]], "on_hand": r["on_hand"],
                         "safety_stock": r["safety_stock"]} for r in data["inventory"]])
    add_all(TransferCost, [{"from_warehouse_id": wh[r["from_warehouse"]], "to_warehouse_id": wh[r["to_warehouse"]],
                            "cost_per_unit": r["cost_per_unit"], "transit_days": r["transit_days"]}
                           for r in data["transfer_costs"]])
    cust = {c.name: c.id for c in add_all(Customer, data["customers"])}

    n_lines = 0
    for o in data["orders"]:
        order = Order(ref=o["ref"], customer_id=cust[o["customer"]], order_date=o["order_date"],
                      due_date=o["due_date"], status=o["status"], sla_penalty=o["sla_penalty"], value=o["value"])
        db.add(order)
        db.flush()
        for ln in o["lines"]:
            db.add(OrderLine(order_id=order.id, sku_id=sku[ln["sku"]], warehouse_id=wh[ln["warehouse"]], qty=ln["qty"]))
            n_lines += 1

    for s in data["shipments"]:
        ship = Shipment(ref=s["ref"], supplier_id=sup[s["supplier"]], carrier=s["carrier"],
                        dest_warehouse_id=wh[s["dest_warehouse"]], promised_eta=s["promised_eta"],
                        current_eta=s["current_eta"], status=s["status"], last_seq=s["last_seq"])
        db.add(ship)
        db.flush()
        for ln in s["lines"]:
            db.add(ShipmentLine(shipment_id=ship.id, sku_id=sku[ln["sku"]], qty_expected=ln["qty_expected"]))
    db.flush()

    counts = {k: len(v) for k, v in data.items()} | {"order_lines": n_lines}
    write_audit(db, actor_id=actor_id, role=role, action="synth.load", entity_type="synth",
                payload={"seed": seed, "counts": counts})
    return counts
