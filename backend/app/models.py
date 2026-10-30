"""SQLAlchemy models for the linked data model (blueprint section 6)."""
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base

Money = Numeric(12, 2)


class Warehouse(Base):
    __tablename__ = "warehouses"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(80), unique=True)
    city: Mapped[str] = mapped_column(String(80))


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    email: Mapped[str] = mapped_column(String(160), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(40))
    warehouse_id: Mapped[int | None] = mapped_column(ForeignKey("warehouses.id"))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class Supplier(Base):
    __tablename__ = "suppliers"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True)
    baseline_lead_days: Mapped[int] = mapped_column(Integer, default=7)
    reliability_score: Mapped[float] = mapped_column(Float, default=80.0)


class Sku(Base):
    __tablename__ = "skus"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(40), unique=True)
    name: Mapped[str] = mapped_column(String(160))
    unit_cost: Mapped[Decimal] = mapped_column(Money, default=0)
    safety_stock_default: Mapped[int] = mapped_column(Integer, default=0)


class SupplierItem(Base):
    __tablename__ = "supplier_items"
    supplier_id: Mapped[int] = mapped_column(ForeignKey("suppliers.id"), primary_key=True)
    sku_id: Mapped[int] = mapped_column(ForeignKey("skus.id"), primary_key=True)
    unit_price: Mapped[Decimal] = mapped_column(Money)
    lead_days: Mapped[int] = mapped_column(Integer)


class Inventory(Base):
    __tablename__ = "inventory"
    warehouse_id: Mapped[int] = mapped_column(ForeignKey("warehouses.id"), primary_key=True)
    sku_id: Mapped[int] = mapped_column(ForeignKey("skus.id"), primary_key=True)
    on_hand: Mapped[int] = mapped_column(Integer, default=0)
    safety_stock: Mapped[int] = mapped_column(Integer, default=0)
    version: Mapped[int] = mapped_column(Integer, default=1)
    __mapper_args__ = {"version_id_col": version}


class TransferCost(Base):
    __tablename__ = "transfer_costs"
    from_warehouse_id: Mapped[int] = mapped_column(ForeignKey("warehouses.id"), primary_key=True)
    to_warehouse_id: Mapped[int] = mapped_column(ForeignKey("warehouses.id"), primary_key=True)
    cost_per_unit: Mapped[Decimal] = mapped_column(Money)
    transit_days: Mapped[int] = mapped_column(Integer)


class Customer(Base):
    __tablename__ = "customers"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    city: Mapped[str] = mapped_column(String(80))
    tier: Mapped[str] = mapped_column(String(10), default="bronze")
    allows_partial: Mapped[bool] = mapped_column(Boolean, default=False)


class Order(Base):
    __tablename__ = "orders"
    id: Mapped[int] = mapped_column(primary_key=True)
    ref: Mapped[str] = mapped_column(String(40), unique=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"))
    order_date: Mapped[date] = mapped_column(Date)
    due_date: Mapped[date] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(20), default="open")
    sla_penalty: Mapped[Decimal] = mapped_column(Money, default=0)
    value: Mapped[Decimal] = mapped_column(Money, default=0)


class OrderLine(Base):
    __tablename__ = "order_lines"
    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"))
    sku_id: Mapped[int] = mapped_column(ForeignKey("skus.id"))
    warehouse_id: Mapped[int] = mapped_column(ForeignKey("warehouses.id"))
    qty: Mapped[int] = mapped_column(Integer)
    qty_allocated: Mapped[int] = mapped_column(Integer, default=0)


class Shipment(Base):
    __tablename__ = "shipments"
    id: Mapped[int] = mapped_column(primary_key=True)
    ref: Mapped[str] = mapped_column(String(40), unique=True)
    supplier_id: Mapped[int] = mapped_column(ForeignKey("suppliers.id"))
    carrier: Mapped[str] = mapped_column(String(60))
    dest_warehouse_id: Mapped[int] = mapped_column(ForeignKey("warehouses.id"))
    promised_eta: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    current_eta: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(20), default="in_transit")
    last_seq: Mapped[int] = mapped_column(Integer, default=0)
    last_scan_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(Integer, default=1)
    __mapper_args__ = {"version_id_col": version}


class ShipmentLine(Base):
    __tablename__ = "shipment_lines"
    shipment_id: Mapped[int] = mapped_column(ForeignKey("shipments.id"), primary_key=True)
    sku_id: Mapped[int] = mapped_column(ForeignKey("skus.id"), primary_key=True)
    qty_expected: Mapped[int] = mapped_column(Integer)
    qty_received: Mapped[int] = mapped_column(Integer, default=0)


class ShipmentEvent(Base):
    __tablename__ = "shipment_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    shipment_id: Mapped[int | None] = mapped_column(ForeignKey("shipments.id"))
    carrier: Mapped[str] = mapped_column(String(60))
    event_type: Mapped[str] = mapped_column(String(40))
    seq: Mapped[int] = mapped_column(Integer)
    payload_json: Mapped[dict] = mapped_column(JSONB, default=dict)
    idem_key: Mapped[str] = mapped_column(String(64), unique=True)
    outcome: Mapped[str] = mapped_column(String(12))
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ImportBatch(Base):
    __tablename__ = "import_batches"
    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(10))  # csv | json
    entity: Mapped[str] = mapped_column(String(40))
    filename: Mapped[str | None] = mapped_column(String(200))
    rows_ok: Mapped[int] = mapped_column(Integer, default=0)
    rows_failed: Mapped[int] = mapped_column(Integer, default=0)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ImportRowError(Base):
    __tablename__ = "import_errors"
    id: Mapped[int] = mapped_column(primary_key=True)
    batch_id: Mapped[int] = mapped_column(ForeignKey("import_batches.id"))
    row_no: Mapped[int] = mapped_column(Integer)
    field: Mapped[str | None] = mapped_column(String(80))
    reason: Mapped[str] = mapped_column(Text)


class Disruption(Base):
    __tablename__ = "disruptions"
    id: Mapped[int] = mapped_column(primary_key=True)
    type: Mapped[str] = mapped_column(String(20))
    shipment_id: Mapped[int | None] = mapped_column(ForeignKey("shipments.id"))
    sku_id: Mapped[int | None] = mapped_column(ForeignKey("skus.id"))
    warehouse_id: Mapped[int | None] = mapped_column(ForeignKey("warehouses.id"))
    severity: Mapped[str] = mapped_column(String(10), default="medium")
    status: Mapped[str] = mapped_column(String(12), default="active")
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    summary_text: Mapped[str | None] = mapped_column(Text)


class OrderRisk(Base):
    __tablename__ = "order_risk"
    __table_args__ = (UniqueConstraint("disruption_id", "order_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    disruption_id: Mapped[int] = mapped_column(ForeignKey("disruptions.id"))
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"))
    score: Mapped[float] = mapped_column(Float)
    band: Mapped[str] = mapped_column(String(10))
    factors_json: Mapped[dict] = mapped_column(JSONB, default=dict)
    rank: Mapped[int] = mapped_column(Integer)


class Plan(Base):
    __tablename__ = "plans"
    id: Mapped[int] = mapped_column(primary_key=True)
    disruption_id: Mapped[int] = mapped_column(ForeignKey("disruptions.id"))
    type: Mapped[str] = mapped_column(String(20))
    params_json: Mapped[dict] = mapped_column(JSONB, default=dict)
    metrics_json: Mapped[dict] = mapped_column(JSONB, default=dict)
    status: Mapped[str] = mapped_column(String(12), default="DRAFT")
    version: Mapped[int] = mapped_column(Integer, default=1)
    proposer_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    modified_by_ids: Mapped[list] = mapped_column(JSONB, default=list)
    approver_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    executor_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    ai_rationale: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    __mapper_args__ = {"version_id_col": version}  # optimistic locking: stale write raises StaleDataError


class PlanStep(Base):
    __tablename__ = "plan_steps"
    id: Mapped[int] = mapped_column(primary_key=True)
    plan_id: Mapped[int] = mapped_column(ForeignKey("plans.id"))
    seq: Mapped[int] = mapped_column(Integer)
    description: Mapped[str] = mapped_column(String(240))
    status: Mapped[str] = mapped_column(String(10), default="pending")
    done_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Notification(Base):
    __tablename__ = "notifications"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    kind: Mapped[str] = mapped_column(String(40))
    message: Mapped[str] = mapped_column(Text)
    entity_ref: Mapped[str | None] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AuditLog(Base):
    """Append-only. UPDATE/DELETE/TRUNCATE are blocked by DB triggers (app/audit/ddl.py)."""

    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    actor_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    role: Mapped[str | None] = mapped_column(String(40))
    action: Mapped[str] = mapped_column(String(60))
    entity_type: Mapped[str] = mapped_column(String(40))
    entity_id: Mapped[str | None] = mapped_column(String(60))
    reason: Mapped[str | None] = mapped_column(Text)
    payload_json: Mapped[dict] = mapped_column(JSONB, default=dict)
    prev_hash: Mapped[str] = mapped_column(String(64))
    row_hash: Mapped[str] = mapped_column(String(64))
