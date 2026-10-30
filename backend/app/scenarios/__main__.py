"""Fire a disruption scenario through the real HTTP endpoints, so every guard runs on camera.

  python -m app.scenarios s1            port delay: carrier webhook pushes SHP-1042 six days late
  python -m app.scenarios s2            partial shipment: SHP-1077 delivers 55%, then a burst of new orders is imported
  python -m app.scenarios s1 --replay   send the same event again (shows the duplicate guard)

The API must be running and the demo data loaded (python -m app.synth --seed 42).
"""
import argparse
import json
import sys
from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy import select

from app.config import settings
from app.db import SessionLocal
from app.ingest.webhook import sign
from app.models import Shipment, ShipmentLine
from app.seed_users import DEMO_PASSWORD
from app.synth.generator import S1_SHIPMENT, S1_SKU, S2_SHIPMENT, S2_SKU

BURST = [  # (order_ref, customer, due in days, qty): new Mumbai demand that arrives after the short delivery
    ("ORD-6101", "Konkan Fabricators", 4, 40), ("ORD-6102", "Western Grid Industries", 5, 45),
    ("ORD-6103", "Thane Hardware Mart", 6, 40), ("ORD-6104", "Sundaram Auto Parts", 8, 35),
]


def _shipment(ref: str) -> tuple[Shipment, list[ShipmentLine]]:
    with SessionLocal() as db:
        ship = db.execute(select(Shipment).where(Shipment.ref == ref)).scalar_one_or_none()
        if ship is None:
            sys.exit(f"{ref} not found. Load demo data first: python -m app.synth --seed 42 --reset")
        lines = list(db.execute(select(ShipmentLine).where(ShipmentLine.shipment_id == ship.id)).scalars())
        db.expunge_all()
        return ship, lines


def _post_event(client: httpx.Client, payload: dict) -> None:
    body = json.dumps(payload).encode()
    r = client.post("/webhooks/carrier", content=body,
                    headers={"Content-Type": "application/json", "X-Signature": sign(body, settings.webhook_secret)})
    print(f"webhook {payload['event_type']} seq={payload['seq']} -> {r.status_code} {r.json()}")


def _login(client: httpx.Client, email: str, password: str) -> dict:
    r = client.post("/auth/login", json={"email": email, "password": password})
    if r.status_code != 200:
        sys.exit(f"login failed for {email}: {r.status_code}")
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def scenario_1(client: httpx.Client, replay: bool) -> None:
    ship, _ = _shipment(S1_SHIPMENT)
    now = datetime.now(timezone.utc)
    seq = ship.last_seq if replay else ship.last_seq + 1
    _post_event(client, {
        "carrier": ship.carrier, "shipment_ref": ship.ref, "event_type": "delayed", "seq": max(seq, 1),
        "occurred_at": now.replace(second=0, microsecond=0).isoformat(),
        "new_eta": (ship.promised_eta + timedelta(days=6)).isoformat(),
        "reason": "Port congestion at Chennai; vessel berthing postponed",
    })


def scenario_2(client: httpx.Client, replay: bool, email: str, password: str) -> None:
    ship, lines = _shipment(S2_SHIPMENT)
    sku_qty = next(ln.qty_expected for ln in lines)
    now = datetime.now(timezone.utc)
    seq = ship.last_seq if replay else ship.last_seq + 1
    _post_event(client, {
        "carrier": ship.carrier, "shipment_ref": ship.ref, "event_type": "partial_delivery", "seq": max(seq, 1),
        "occurred_at": now.replace(second=0, microsecond=0).isoformat(),
        "received": [{"sku": S2_SKU, "qty": round(sku_qty * 0.55)}],
        "new_eta": (ship.promised_eta + timedelta(days=10)).isoformat(),
        "reason": "Supplier shipped 55% of the PO; balance rescheduled",
    })
    today = datetime.now().date()
    rows = [{"order_ref": ref, "customer": cust, "order_date": today.isoformat(),
             "due_date": (today + timedelta(days=due)).isoformat(), "sku": S2_SKU, "warehouse": "Mumbai", "qty": qty,
             "sla_penalty": 10000} for ref, cust, due, qty in BURST]
    r = client.post("/import/json", headers=_login(client, email, password), json={"entity": "orders", "rows": rows})
    out = r.json()
    print(f"import burst -> {r.status_code}: ok={out.get('rows_ok')} failed={out.get('rows_failed')}")
    for e in out.get("errors", []):
        print(f"  row {e['row_no']}: {e['reason']}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("scenario", choices=["s1", "s2"])
    ap.add_argument("--base-url", default="http://localhost:8000")
    ap.add_argument("--replay", action="store_true", help="resend the last event (duplicate guard demo)")
    ap.add_argument("--email", default="analyst@diq.test")
    ap.add_argument("--password", default=DEMO_PASSWORD)
    args = ap.parse_args()
    with httpx.Client(base_url=args.base_url, timeout=15) as client:
        if args.scenario == "s1":
            scenario_1(client, args.replay)
        else:
            scenario_2(client, args.replay, args.email, args.password)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
