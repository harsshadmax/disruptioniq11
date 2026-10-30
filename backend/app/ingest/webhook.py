"""Simulated carrier webhook: validation, idempotency, stale-event handling (blueprint section 5).

Outcomes, all stored in shipment_events and audited:
  applied    new event, seq ahead of the shipment's last_seq, shipment updated
  duplicate  same idem_key already stored; nothing changes
  stale      seq <= last_seq (out of order / replay) or shipment already delivered; nothing changes
  invalid    unknown shipment, wrong carrier, or lines that do not match the shipment; nothing changes
A payload that fails schema validation never reaches here: the router answers 422 and audits it.
"""
import hashlib
import hmac
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Annotated, Literal

from pydantic import BaseModel, Field, StringConstraints, model_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.audit.service import write_audit
from app.enums import EventOutcome
from app.models import Inventory, Shipment, ShipmentEvent, ShipmentLine, Sku

EventType = Literal["picked_up", "in_transit", "delayed", "eta_update", "partial_delivery", "delivered", "exception"]
WEBHOOK_ROLE = "carrier_webhook"


class ReceivedLine(BaseModel):
    sku: Annotated[str, StringConstraints(min_length=1, max_length=40)]
    qty: int = Field(gt=0, le=1_000_000)


class CarrierEvent(BaseModel):
    carrier: Annotated[str, StringConstraints(min_length=1, max_length=60, strip_whitespace=True)]
    shipment_ref: Annotated[str, StringConstraints(min_length=1, max_length=40, pattern=r"^[A-Za-z0-9._-]+$")]
    event_type: EventType
    seq: int = Field(ge=1, le=2_000_000_000)
    occurred_at: datetime
    new_eta: datetime | None = None
    reason: str | None = Field(default=None, max_length=200)
    received: list[ReceivedLine] | None = Field(default=None, max_length=50)

    @model_validator(mode="after")
    def _check(self) -> "CarrierEvent":
        if self.occurred_at.tzinfo is None:
            raise ValueError("occurred_at must include a timezone offset")
        if self.new_eta is not None and self.new_eta.tzinfo is None:
            raise ValueError("new_eta must include a timezone offset")
        if self.event_type in ("delayed", "eta_update") and self.new_eta is None:
            raise ValueError(f"{self.event_type} requires new_eta")
        if self.event_type == "partial_delivery" and not self.received:
            raise ValueError("partial_delivery requires received lines")
        return self


def sign(body: bytes, secret: str) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def signature_ok(body: bytes, header: str | None, secret: str) -> bool:
    return header is not None and hmac.compare_digest(sign(body, secret), header)


def idem_key(event: CarrierEvent) -> str:
    bucket = event.occurred_at.astimezone(timezone.utc).strftime("%Y%m%dT%H%M")  # one-minute bucket
    raw = f"{event.carrier.lower()}|{event.shipment_ref}|{event.event_type}|{bucket}"
    return hashlib.sha256(raw.encode()).hexdigest()


@dataclass
class WebhookResult:
    outcome: str
    status_code: int
    detail: str | None = None
    event_id: int | None = None
    shipment_ref: str | None = None


class _Rejected(Exception):
    pass


def _flow_status(ship: Shipment) -> str:
    return "delayed" if ship.current_eta > ship.promised_eta else "in_transit"


def _receive(db: Session, ship: Shipment, event: CarrierEvent) -> None:
    lines = {sl.sku_id: sl for sl in db.execute(select(ShipmentLine).where(ShipmentLine.shipment_id == ship.id)).scalars()}
    codes = {s.code: s.id for s in db.execute(select(Sku).where(Sku.id.in_(lines))).scalars()}
    wanted: dict[int, int] = {}
    if event.received:
        for r in event.received:
            if r.sku not in codes:
                raise _Rejected(f"SKU {r.sku} is not on shipment {ship.ref}")
            wanted[codes[r.sku]] = wanted.get(codes[r.sku], 0) + r.qty
    else:  # "delivered" with no lines means everything outstanding arrived
        wanted = {sku_id: sl.qty_expected - sl.qty_received for sku_id, sl in lines.items()}
    for sku_id, qty in wanted.items():
        sl = lines[sku_id]
        if sl.qty_received + qty > sl.qty_expected:
            raise _Rejected(f"received {qty} would exceed the {sl.qty_expected} expected for SKU id {sku_id}")
        sl.qty_received += qty
        inv = db.get(Inventory, (ship.dest_warehouse_id, sku_id))
        if inv is None:
            db.add(Inventory(warehouse_id=ship.dest_warehouse_id, sku_id=sku_id, on_hand=qty, safety_stock=0))
        else:
            inv.on_hand += qty
    complete = all(sl.qty_received >= sl.qty_expected for sl in lines.values())
    ship.status = "delivered" if complete else "partially_received"


def _apply(db: Session, ship: Shipment, event: CarrierEvent) -> None:
    t = event.event_type
    if event.new_eta is not None:
        ship.current_eta = event.new_eta
    if t in ("picked_up", "in_transit", "delayed", "eta_update"):
        ship.status = _flow_status(ship)
    elif t == "exception":
        ship.status = "exception"
    else:  # partial_delivery, delivered
        _receive(db, ship, event)
    ship.last_seq = event.seq
    if ship.last_scan_at is None or event.occurred_at > ship.last_scan_at:
        ship.last_scan_at = event.occurred_at
    db.flush()


def _audit(db: Session, outcome: str, event: CarrierEvent, key: str, reason: str | None = None) -> None:
    write_audit(db, actor_id=None, role=WEBHOOK_ROLE, action=f"webhook.{outcome}", entity_type="shipment",
                entity_id=event.shipment_ref, reason=reason,
                payload={"carrier": event.carrier, "event_type": event.event_type, "seq": event.seq,
                         "idem_key": key[:16]})


def process_event(db: Session, event: CarrierEvent) -> WebhookResult:
    key = idem_key(event)
    ship = db.execute(select(Shipment).where(Shipment.ref == event.shipment_ref).with_for_update()).scalar_one_or_none()

    def duplicate(existing: ShipmentEvent) -> WebhookResult:
        _audit(db, EventOutcome.DUPLICATE, event, key, f"same as event {existing.id}")
        return WebhookResult(EventOutcome.DUPLICATE, 200, f"already processed as event {existing.id}",
                             existing.id, event.shipment_ref)

    def finish(outcome: str, status_code: int, detail: str | None) -> WebhookResult:
        row = ShipmentEvent(shipment_id=ship.id if ship else None, carrier=event.carrier,
                            event_type=event.event_type, seq=event.seq, idem_key=key, outcome=outcome,
                            payload_json=event.model_dump(mode="json"))
        try:
            with db.begin_nested():
                db.add(row)
        except IntegrityError:  # lost a race on the UNIQUE idem_key: the other request stored it first
            return duplicate(db.execute(select(ShipmentEvent).where(ShipmentEvent.idem_key == key)).scalar_one())
        _audit(db, outcome, event, key, detail)
        return WebhookResult(outcome, status_code, detail, row.id, event.shipment_ref)

    existing = db.execute(select(ShipmentEvent).where(ShipmentEvent.idem_key == key)).scalar_one_or_none()
    if existing is not None:
        return duplicate(existing)
    if ship is None:
        return finish(EventOutcome.INVALID, 404, f"unknown shipment {event.shipment_ref}")
    if ship.carrier.lower() != event.carrier.lower():
        return finish(EventOutcome.INVALID, 422, f"carrier {event.carrier} does not own shipment {ship.ref}")
    if event.seq <= ship.last_seq:
        return finish(EventOutcome.STALE, 200, f"seq {event.seq} <= last applied seq {ship.last_seq}")
    if ship.status == "delivered":
        return finish(EventOutcome.STALE, 200, "shipment already delivered")
    try:
        with db.begin_nested():
            _apply(db, ship, event)
    except _Rejected as exc:
        return finish(EventOutcome.INVALID, 422, str(exc))
    return finish(EventOutcome.APPLIED, 200, None)
