import json
from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select

from app.audit.service import verify_chain
from app.config import settings
from app.ingest.webhook import CarrierEvent, idem_key, sign
from app.models import AuditLog, Inventory, Shipment, ShipmentEvent, ShipmentLine, Sku, Warehouse
from app.synth.generator import generate
from app.synth.loader import load_synth

TODAY = date(2026, 11, 2)
S1_CARRIER, S2_CARRIER = "SeaLink Logistics", "RoadRunner Freight"


@pytest.fixture
def world(db):
    load_synth(db, generate(42, TODAY), seed=42)
    return db


def send(client, payload, *, signed=True, raw: bytes | None = None, secret=None):
    body = raw if raw is not None else json.dumps(payload).encode()
    headers = {"Content-Type": "application/json"}
    if signed:
        headers["X-Signature"] = sign(body, secret or settings.webhook_secret)
    return client.post("/webhooks/carrier", content=body, headers=headers)


def event(**over):
    base = {"carrier": S1_CARRIER, "shipment_ref": "SHP-1042", "event_type": "delayed", "seq": 1,
            "occurred_at": "2026-11-02T08:00:00Z", "new_eta": "2026-11-11T10:00:00Z", "reason": "port congestion"}
    base.update(over)
    return {k: v for k, v in base.items() if v is not None}


def ship(db, ref="SHP-1042") -> Shipment:
    db.expire_all()
    return db.execute(select(Shipment).where(Shipment.ref == ref)).scalar_one()


def audit_actions(db, prefix="webhook."):
    return [a for a in db.execute(select(AuditLog.action).order_by(AuditLog.id)).scalars() if a.startswith(prefix)]


def n_events(db):
    return db.execute(select(func.count(ShipmentEvent.id))).scalar_one()


def test_delay_event_is_applied_stored_and_audited(client, world):
    r = send(client, event())
    assert r.status_code == 200 and r.json()["outcome"] == "applied"
    s = ship(world)
    assert s.current_eta == datetime(2026, 11, 11, 10, tzinfo=timezone.utc)
    assert s.promised_eta == datetime(2026, 11, 5, 10, tzinfo=timezone.utc)  # the promise is never rewritten
    assert s.status == "delayed" and s.last_seq == 1 and s.last_scan_at is not None
    ev = world.execute(select(ShipmentEvent)).scalar_one()
    assert ev.outcome == "applied" and ev.payload_json["reason"] == "port congestion"
    assert audit_actions(world) == ["webhook.applied"]


def test_duplicate_is_acknowledged_and_changes_nothing(client, world):
    assert send(client, event()).json()["outcome"] == "applied"
    version_after_first = ship(world).version
    again = send(client, event())
    assert again.status_code == 200 and again.json()["outcome"] == "duplicate"
    assert n_events(world) == 1
    assert ship(world).version == version_after_first
    assert audit_actions(world) == ["webhook.applied", "webhook.duplicate"]


def test_carrier_retry_with_a_new_seq_in_the_same_minute_is_still_a_duplicate(client, world):
    send(client, event(seq=1))
    assert send(client, event(seq=2, occurred_at="2026-11-02T08:00:41Z")).json()["outcome"] == "duplicate"
    assert ship(world).last_seq == 1


def test_idem_key_rules():
    a = CarrierEvent(**event())
    assert idem_key(a) == idem_key(CarrierEvent(**event(carrier=S1_CARRIER.upper())))
    assert idem_key(a) != idem_key(CarrierEvent(**event(occurred_at="2026-11-02T08:01:00Z")))
    assert idem_key(a) != idem_key(CarrierEvent(**event(event_type="eta_update")))
    assert idem_key(a) == idem_key(CarrierEvent(**event(occurred_at="2026-11-02T13:30:30+05:30")))  # same instant


def test_out_of_order_event_is_stored_as_stale_and_ignored(client, world):
    send(client, event(seq=5, new_eta="2026-11-11T10:00:00Z"))
    old = send(client, event(seq=3, event_type="eta_update", occurred_at="2026-11-02T07:00:00Z",
                             new_eta="2026-11-06T10:00:00Z"))
    assert old.status_code == 200 and old.json()["outcome"] == "stale"
    s = ship(world)
    assert s.current_eta == datetime(2026, 11, 11, 10, tzinfo=timezone.utc) and s.last_seq == 5
    stale = world.execute(select(ShipmentEvent).where(ShipmentEvent.outcome == "stale")).scalar_one()
    assert stale.seq == 3
    assert audit_actions(world) == ["webhook.applied", "webhook.stale"]


def test_same_seq_is_stale_too(client, world):
    send(client, event(seq=4))
    r = send(client, event(seq=4, event_type="eta_update", occurred_at="2026-11-02T09:00:00Z"))
    assert r.json()["outcome"] == "stale"


@pytest.mark.parametrize("payload,field", [
    (event(new_eta=None), "new_eta"),                                   # delayed needs an ETA
    (event(occurred_at="2026-11-02T08:00:00"), "occurred_at"),          # no timezone
    (event(event_type="teleported"), "event_type"),
    (event(seq=0), "seq"),
    (event(seq="abc"), "seq"),
    (event(shipment_ref="SHP 1042; DROP TABLE"), "shipment_ref"),
    (event(carrier=""), "carrier"),
    ({k: v for k, v in event().items() if k != "shipment_ref"}, "shipment_ref"),
])
def test_invalid_payload_is_422_audited_and_changes_nothing(client, world, payload, field):
    r = send(client, payload)
    assert r.status_code == 422
    assert any(p["field"] and field in p["field"] or field in p["reason"] for p in r.json()["detail"])
    assert n_events(world) == 0 and ship(world).last_seq == 0
    assert audit_actions(world) == ["webhook.invalid"]


def test_non_json_body_is_422(client, world):
    assert send(client, None, raw=b"this is not json").status_code == 422
    assert audit_actions(world) == ["webhook.invalid"]


def test_unsigned_or_wrongly_signed_requests_are_rejected_and_audited(client, world):
    assert send(client, event(), signed=False).status_code == 401
    assert send(client, event(), secret="someone-elses-secret").status_code == 401
    assert n_events(world) == 0 and ship(world).last_seq == 0
    assert audit_actions(world) == ["webhook.unauthorized", "webhook.unauthorized"]


def test_tampered_body_fails_the_signature(client, world):
    body = json.dumps(event()).encode()
    headers = {"X-Signature": sign(body, settings.webhook_secret), "Content-Type": "application/json"}
    r = client.post("/webhooks/carrier", content=body.replace(b"2026-11-11", b"2026-12-31"), headers=headers)
    assert r.status_code == 401


def test_unknown_shipment_is_404_and_recorded_as_invalid(client, world):
    r = send(client, event(shipment_ref="SHP-0000"))
    assert r.status_code == 404
    ev = world.execute(select(ShipmentEvent)).scalar_one()
    assert ev.outcome == "invalid" and ev.shipment_id is None
    assert send(client, event(shipment_ref="SHP-0000")).json()["outcome"] == "duplicate"  # retries don't pile up


def test_event_from_the_wrong_carrier_is_invalid(client, world):
    r = send(client, event(carrier=S2_CARRIER))
    assert r.status_code == 422 and r.json()["outcome"] == "invalid"
    assert ship(world).last_seq == 0 and ship(world).status == "in_transit"


def test_partial_delivery_updates_receipt_stock_and_status(client, world):
    sku = world.execute(select(Sku).where(Sku.code == "SKU-006")).scalar_one()
    mumbai = world.execute(select(Warehouse).where(Warehouse.name == "Mumbai")).scalar_one()
    before = world.get(Inventory, (mumbai.id, sku.id)).on_hand
    r = send(client, event(carrier=S2_CARRIER, shipment_ref="SHP-1077", event_type="partial_delivery",
                           received=[{"sku": "SKU-006", "qty": 220}], new_eta="2026-11-14T10:00:00Z"))
    assert r.json()["outcome"] == "applied"
    s = ship(world, "SHP-1077")
    line = world.execute(select(ShipmentLine).where(ShipmentLine.shipment_id == s.id)).scalar_one()
    assert s.status == "partially_received" and line.qty_received == 220
    assert s.current_eta == datetime(2026, 11, 14, 10, tzinfo=timezone.utc)
    world.expire_all()
    assert world.get(Inventory, (mumbai.id, sku.id)).on_hand == before + 220


def test_over_receiving_is_rejected_and_nothing_is_half_applied(client, world):
    sku1 = world.execute(select(Sku).where(Sku.code == "SKU-006")).scalar_one()
    sku2 = world.execute(select(Sku).where(Sku.code == "SKU-007")).scalar_one()
    s = ship(world, "SHP-1077")
    world.add(ShipmentLine(shipment_id=s.id, sku_id=sku2.id, qty_expected=50))
    world.flush()
    mumbai = world.execute(select(Warehouse).where(Warehouse.name == "Mumbai")).scalar_one()
    before = world.get(Inventory, (mumbai.id, sku1.id)).on_hand
    r = send(client, event(carrier=S2_CARRIER, shipment_ref="SHP-1077", event_type="partial_delivery",
                           received=[{"sku": "SKU-006", "qty": 100}, {"sku": "SKU-007", "qty": 999}]))
    assert r.status_code == 422 and r.json()["outcome"] == "invalid"
    world.expire_all()
    assert world.get(Inventory, (mumbai.id, sku1.id)).on_hand == before
    assert world.execute(select(func.sum(ShipmentLine.qty_received))).scalar_one() == 0
    assert ship(world, "SHP-1077").last_seq == 0


def test_sku_not_on_the_shipment_is_invalid(client, world):
    r = send(client, event(carrier=S2_CARRIER, shipment_ref="SHP-1077", event_type="partial_delivery",
                           received=[{"sku": "SKU-020", "qty": 5}]))
    assert r.status_code == 422 and "not on shipment" in r.json()["detail"]


def test_delivered_without_lines_receives_the_rest_and_closes_the_shipment(client, world):
    send(client, event(carrier=S2_CARRIER, shipment_ref="SHP-1077", event_type="partial_delivery", seq=1,
                       received=[{"sku": "SKU-006", "qty": 220}]))
    r = send(client, event(carrier=S2_CARRIER, shipment_ref="SHP-1077", event_type="delivered", seq=2,
                           new_eta=None, occurred_at="2026-11-04T09:00:00Z"))
    assert r.json()["outcome"] == "applied"
    s = ship(world, "SHP-1077")
    assert s.status == "delivered"
    assert world.execute(select(ShipmentLine.qty_received).where(ShipmentLine.shipment_id == s.id)).scalar_one() == 400
    late = send(client, event(carrier=S2_CARRIER, shipment_ref="SHP-1077", event_type="delayed", seq=3,
                              occurred_at="2026-11-05T09:00:00Z"))
    assert late.json()["outcome"] == "stale" and "delivered" in late.json()["detail"]


def test_recovered_eta_returns_to_in_transit(client, world):
    send(client, event(seq=1))
    r = send(client, event(seq=2, event_type="eta_update", occurred_at="2026-11-02T10:00:00Z",
                           new_eta="2026-11-05T10:00:00Z"))
    assert r.json()["outcome"] == "applied" and ship(world).status == "in_transit"


def test_exception_event_flags_the_shipment(client, world):
    send(client, event(event_type="exception", new_eta=None, reason="customs hold"))
    assert ship(world).status == "exception"


def test_audit_chain_is_intact_after_every_outcome(client, world):
    send(client, event(seq=2))
    send(client, event(seq=2))                                             # duplicate
    send(client, event(seq=1, event_type="eta_update", new_eta="2026-11-06T10:00:00Z",
                       occurred_at="2026-11-02T06:00:00Z"))                # stale
    send(client, event(new_eta=None))                                      # invalid payload
    send(client, event(), signed=False)                                    # unauthorized
    assert audit_actions(world) == ["webhook.applied", "webhook.duplicate", "webhook.stale", "webhook.invalid",
                                    "webhook.unauthorized"]
    assert verify_chain(world)[0] is True
