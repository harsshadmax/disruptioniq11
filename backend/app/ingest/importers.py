"""CSV / JSON import with row-level validation (blueprint section 5).

Both formats become a list of (row_no, dict) and go through the same pipeline:
  1. every row is validated by a Pydantic model (types, positive quantities, due date after order date)
  2. rows that belong together (the lines of one order) are grouped; one bad line rejects the whole group,
     so an order is never imported half-complete
  3. each valid group is applied inside a savepoint (known customer/SKU/warehouse, no overwrite of existing orders)
  4. good rows are kept, bad rows are written to import_errors with a reason, and a batch summary is returned
"""
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Annotated, Any, Callable

from pydantic import (
    BaseModel, ConfigDict, Field, StringConstraints, ValidationError, ValidationInfo, field_validator, model_validator,
)
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    Customer, ImportBatch, ImportRowError, Inventory, Order, OrderLine, Shipment, ShipmentLine, Sku, Supplier, Warehouse,
)

Ref = Annotated[str, StringConstraints(min_length=1, max_length=40, pattern=r"^[A-Za-z0-9._-]+$")]
Name = Annotated[str, StringConstraints(min_length=1, max_length=120)]
Money = Annotated[Decimal, Field(ge=0, max_digits=10, decimal_places=2)]
Qty = Annotated[int, Field(gt=0, le=1_000_000)]


class _Row(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="ignore")

    @model_validator(mode="before")
    @classmethod
    def _blank_means_missing(cls, data: Any) -> Any:  # empty CSV cells and JSON nulls behave like absent fields
        return {k: v for k, v in data.items() if v is not None} if isinstance(data, dict) else data


class OrderRow(_Row):
    order_ref: Ref
    customer: Name
    order_date: date
    due_date: date
    sku: Name
    warehouse: Name
    qty: Qty
    sla_penalty: Money = Decimal("0")
    value: Money | None = None

    @field_validator("due_date")
    @classmethod
    def _due_after_order(cls, v: date, info: ValidationInfo) -> date:
        order_date = info.data.get("order_date")
        if order_date is not None and v <= order_date:
            raise ValueError("due_date must be after order_date")
        return v


class InventoryRow(_Row):
    warehouse: Name
    sku: Name
    on_hand: Annotated[int, Field(ge=0, le=10_000_000)]
    safety_stock: Annotated[int, Field(ge=0, le=10_000_000)] | None = None


class ShipmentRow(_Row):
    shipment_ref: Ref
    supplier: Name
    carrier: Annotated[str, StringConstraints(min_length=1, max_length=60)]
    dest_warehouse: Name
    promised_eta: datetime  # a missing timezone is read as UTC
    sku: Name
    qty: Qty

    @field_validator("promised_eta")
    @classmethod
    def _utc(cls, v: datetime) -> datetime:
        return v.replace(tzinfo=timezone.utc) if v.tzinfo is None else v.astimezone(timezone.utc)


class RowError(Exception):
    """Business-rule failure for one row of a group (row_no=None means the first row of the group)."""

    def __init__(self, field: str | None, reason: str, row_no: int | None = None):
        super().__init__(reason)
        self.field, self.reason, self.row_no = field, reason, row_no


@dataclass
class Parsed:
    row_no: int
    data: Any


def _by_name(db: Session, model, column, value: str):
    return db.execute(select(model).where(func.lower(column) == value.lower())).scalar_one_or_none()


def _lookup(db: Session, model, column, value: str, field: str, label: str, row_no: int):
    obj = _by_name(db, model, column, value)
    if obj is None:
        raise RowError(field, f"unknown {label} '{value}'", row_no)
    return obj


def _consistent(rows: list[Parsed], fields: tuple[str, ...], what: str) -> None:
    first = rows[0].data
    for p in rows[1:]:
        for f in fields:
            if getattr(p.data, f) != getattr(first, f):
                raise RowError(f, f"{f} differs from the first line of this {what}", p.row_no)


def _apply_orders(db: Session, key: str, rows: list[Parsed]) -> None:
    head = rows[0].data
    if db.execute(select(Order.id).where(Order.ref == head.order_ref)).first():
        raise RowError("order_ref", f"order '{head.order_ref}' already exists; imports never overwrite orders", rows[0].row_no)
    _consistent(rows, ("customer", "order_date", "due_date", "sla_penalty", "value"), "order")
    customer = _lookup(db, Customer, Customer.name, head.customer, "customer", "customer", rows[0].row_no)
    lines, seen, total = [], set(), Decimal("0")
    for p in rows:
        sku = _lookup(db, Sku, Sku.code, p.data.sku, "sku", "SKU", p.row_no)
        wh = _lookup(db, Warehouse, Warehouse.name, p.data.warehouse, "warehouse", "warehouse", p.row_no)
        if (sku.id, wh.id) in seen:
            raise RowError("sku", f"duplicate line for {sku.code} at {wh.name} in this order", p.row_no)
        seen.add((sku.id, wh.id))
        lines.append((sku.id, wh.id, p.data.qty))
        total += sku.unit_cost * p.data.qty
    value = head.value if head.value is not None else (total * Decimal("1.35")).quantize(Decimal("0.01"))
    order = Order(ref=head.order_ref, customer_id=customer.id, order_date=head.order_date, due_date=head.due_date,
                  status="open", sla_penalty=head.sla_penalty, value=value)
    db.add(order)
    db.flush()
    for sku_id, wh_id, qty in lines:
        db.add(OrderLine(order_id=order.id, sku_id=sku_id, warehouse_id=wh_id, qty=qty))


def _apply_inventory(db: Session, key: str, rows: list[Parsed]) -> None:
    if len(rows) > 1:
        raise RowError("sku", "duplicate warehouse/SKU row in this file", rows[1].row_no)
    p = rows[0]
    wh = _lookup(db, Warehouse, Warehouse.name, p.data.warehouse, "warehouse", "warehouse", p.row_no)
    sku = _lookup(db, Sku, Sku.code, p.data.sku, "sku", "SKU", p.row_no)
    inv = db.get(Inventory, (wh.id, sku.id))
    if inv is None:
        db.add(Inventory(warehouse_id=wh.id, sku_id=sku.id, on_hand=p.data.on_hand,
                         safety_stock=p.data.safety_stock if p.data.safety_stock is not None else sku.safety_stock_default))
    else:
        inv.on_hand = p.data.on_hand
        if p.data.safety_stock is not None:
            inv.safety_stock = p.data.safety_stock
    db.flush()


def _apply_shipments(db: Session, key: str, rows: list[Parsed]) -> None:
    head = rows[0].data
    if db.execute(select(Shipment.id).where(Shipment.ref == head.shipment_ref)).first():
        raise RowError("shipment_ref", f"shipment '{head.shipment_ref}' already exists; imports never overwrite shipments",
                       rows[0].row_no)
    _consistent(rows, ("supplier", "carrier", "dest_warehouse", "promised_eta"), "shipment")
    sup = _lookup(db, Supplier, Supplier.name, head.supplier, "supplier", "supplier", rows[0].row_no)
    dest = _lookup(db, Warehouse, Warehouse.name, head.dest_warehouse, "dest_warehouse", "warehouse", rows[0].row_no)
    lines, seen = [], set()
    for p in rows:
        sku = _lookup(db, Sku, Sku.code, p.data.sku, "sku", "SKU", p.row_no)
        if sku.id in seen:
            raise RowError("sku", f"duplicate line for {sku.code} in this shipment", p.row_no)
        seen.add(sku.id)
        lines.append((sku.id, p.data.qty))
    ship = Shipment(ref=head.shipment_ref, supplier_id=sup.id, carrier=head.carrier, dest_warehouse_id=dest.id,
                    promised_eta=head.promised_eta, current_eta=head.promised_eta, status="in_transit", last_seq=0)
    db.add(ship)
    db.flush()
    for sku_id, qty in lines:
        db.add(ShipmentLine(shipment_id=ship.id, sku_id=sku_id, qty_expected=qty))


@dataclass(frozen=True)
class EntitySpec:
    model: type[_Row]
    columns: tuple[str, ...]  # required CSV headers
    group_key: Callable[[dict], str | None]  # computed from the raw row so even invalid rows can be grouped
    apply: Callable[[Session, str, list[Parsed]], None]
    group_label: str


def _key(*fields: str) -> Callable[[dict], str | None]:
    def key(raw: dict) -> str | None:
        parts = [str(raw.get(f) or "").strip().lower() for f in fields]
        return "|".join(parts) if all(parts) else None

    return key


SPECS: dict[str, EntitySpec] = {
    "orders": EntitySpec(OrderRow, ("order_ref", "customer", "order_date", "due_date", "sku", "warehouse", "qty"),
                         _key("order_ref"), _apply_orders, "order"),
    "inventory": EntitySpec(InventoryRow, ("warehouse", "sku", "on_hand"), _key("warehouse", "sku"),
                            _apply_inventory, "warehouse/SKU pair"),
    "shipments": EntitySpec(ShipmentRow, ("shipment_ref", "supplier", "carrier", "dest_warehouse", "promised_eta",
                                          "sku", "qty"), _key("shipment_ref"), _apply_shipments, "shipment"),
}


def _loc(err: dict) -> str | None:
    return ".".join(str(p) for p in err["loc"]) or None


def _clean_message(err: dict) -> str:
    msg = err["msg"]
    return msg[len("Value error, "):] if msg.startswith("Value error, ") else msg


def run_import(db: Session, *, entity: str, rows: list[tuple[int, Any]], source: str, filename: str | None,
               user_id: int | None) -> tuple[ImportBatch, list[ImportRowError]]:
    spec = SPECS[entity]
    errors: list[tuple[int, str | None, str]] = []
    groups: dict[str, list[Parsed]] = {}
    bad_groups: dict[str, int] = {}  # group key -> row_no of the first invalid row
    failed_rows: set[int] = set()

    for row_no, raw in rows:
        if not isinstance(raw, dict):
            errors.append((row_no, None, raw if isinstance(raw, str) else "row is not an object with named fields"))
            failed_rows.add(row_no)
            continue
        key = spec.group_key(raw)
        try:
            parsed = spec.model.model_validate(raw)
        except ValidationError as exc:
            for err in exc.errors():
                errors.append((row_no, _loc(err), _clean_message(err)))
            failed_rows.add(row_no)
            if key is not None:
                bad_groups.setdefault(key, row_no)
            continue
        groups.setdefault(key or f"row-{row_no}", []).append(Parsed(row_no, parsed))

    ok_rows = 0
    for key, group in groups.items():
        if key in bad_groups:
            for p in group:
                errors.append((p.row_no, None, f"not imported: row {bad_groups[key]} of the same {spec.group_label} is invalid"))
                failed_rows.add(p.row_no)
            continue
        try:
            with db.begin_nested():
                spec.apply(db, key, group)
            ok_rows += len(group)
        except RowError as exc:
            bad_row = exc.row_no if exc.row_no is not None else group[0].row_no
            errors.append((bad_row, exc.field, exc.reason))
            for p in group:
                failed_rows.add(p.row_no)
                if p.row_no != bad_row:
                    errors.append((p.row_no, None, f"not imported: row {bad_row} of the same {spec.group_label} failed"))

    errors.sort(key=lambda e: e[0])
    batch = ImportBatch(source=source, entity=entity, filename=filename, rows_ok=ok_rows, rows_failed=len(failed_rows),
                        created_by=user_id)
    db.add(batch)
    db.flush()
    error_rows = [ImportRowError(batch_id=batch.id, row_no=n, field=f, reason=r) for n, f, r in errors]
    db.add_all(error_rows)
    db.flush()
    return batch, error_rows
