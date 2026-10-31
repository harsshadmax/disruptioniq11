"""Showcase data: situations in every city and every plan status, driven through the product's own doors.

  python -m app.synth.showcase              straight into the local database (needs the base demo data; runs once)
  python -m app.synth.showcase --dry-run    the same, printed, then rolled back
  python -m app.synth.showcase --extra      add customer contracts and more plans waiting in each approval queue
                                            (for a database or API that already holds the showcase; also works with --api)
  python -m app.synth.showcase --api https://<service>.onrender.com --password <DEMO_PASSWORD> \\
        --webhook-secret <WEBHOOK_SECRET> --base-date 2026-10-30        through a deployed API (no database access needed)

Nothing is inserted by hand. Orders, stock and shipments come in through the importers, carrier events through the
webhook processor, and plans move through propose / modify / approve / reject / execute as the people who hold those
permissions, so every guard runs and every audit row, notification and disruption is the real thing. The base data
(`python -m app.synth --seed 42`) and the two scripted scenarios (`python -m app.scenarios s1|s2`) are left alone.
The two modes run the same script (`episodes`); only the way each step reaches the system differs.
"""
import argparse
import csv
import io
import json
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

import httpx
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.act import service as act
from app.act.errors import Conflict, Forbidden, Invalid, NotFound
from app.config import settings
from app.contracts import service as contracts
from app.contracts.rules import Terms
from app.db import SessionLocal
from app.detect.service import run_detection
from app.enums import PlanStatus, PlanType, Role
from app.ingest.importers import run_import
from app.ingest.webhook import CarrierEvent, ReceivedLine, process_event, sign
from app.models import (
    Customer, CustomerContract, Disruption, Notification, Order, Plan, Shipment, ShipmentEvent, Sku, User, Warehouse,
)
from app.seed_users import DEMO_PASSWORD
from app.synth.pdfmaker import CONTRACT_LINES, make_pdf

MARKER_ORDER, MARKER_FILE = "SHW-M01", "orders_week44.csv"
EXTRA_ORDER, EXTRA_CONTRACT = "SHW-A01", "sundaram_supply_agreement_2025.pdf"  # what marks the extras as loaded
MANAGER_APPROVES = {PlanType.REALLOCATE, PlanType.SPLIT}  # the matrix: managers approve and operators execute these
ROLE_EMAIL = {Role.ANALYST: "analyst@diq.test", Role.MANAGER: "manager@diq.test", Role.OPERATOR: "operator@diq.test",
              Role.PROCUREMENT: "procurement@diq.test"}


@dataclass
class PlanRef:
    id: int
    type: str
    version: int
    params: dict


@dataclass
class DisruptionRef:
    id: int


class Showcase:
    """What the script may do. Subclasses say how each thing reaches the system."""

    def __init__(self) -> None:
        self.now = datetime.now(timezone.utc).replace(second=0, microsecond=0)
        self.today = self.now.date()
        self.sent: dict[str, CarrierEvent] = {}

    # to implement: ship_info, import_rows, deliver, disruption, draft, plan, act_on, tidy_inbox
    def ship_info(self, ref: str) -> tuple[str, datetime, int] | None:
        """(carrier, promised ETA, last applied seq) of a shipment, or None if it does not exist."""
        raise NotImplementedError

    def import_rows(self, entity: str, rows: list[dict], *, filename: str | None = None) -> list[dict]:
        """Import as the analyst; a filename means it arrives as a CSV file. Returns the rejected rows."""
        raise NotImplementedError

    def deliver(self, ev: CarrierEvent) -> str:
        raise NotImplementedError

    def disruption(self, wh: str, sku: str) -> DisruptionRef:
        raise NotImplementedError

    def draft(self, d: DisruptionRef, *prefer: str) -> PlanRef:
        raise NotImplementedError

    def plan(self, plan_id: int) -> PlanRef:
        raise NotImplementedError

    def act_on(self, role: Role, action: str, plan: PlanRef, **body) -> PlanRef | None:
        """Perform an action as `role`. Returns the plan, or None if the rules refused (the refusal is audited)."""
        raise NotImplementedError

    def contract_upload(self, customer: str, filename: str, lines: list[str]) -> tuple[int, dict]:
        """Upload a contract PDF as the analyst. Returns the contract id and the terms the reader proposed."""
        raise NotImplementedError

    def contract_decide(self, contract_id: int, action: str, terms: dict | None = None) -> None:
        """Confirm (with these terms) or reject a pending contract, as the manager."""
        raise NotImplementedError

    def tidy_inbox(self) -> None:
        pass

    # --- shared ------------------------------------------------------------------------------------------------

    def _due(self, ship_ref: str, days_after_eta: int) -> str:
        eta = self.ship_info(ship_ref)[1].date()
        return max(eta + timedelta(days=days_after_eta), self.today + timedelta(days=3)).isoformat()

    def orders(self, wh: str, sku: str, ship_ref: str, rows: list[tuple[str, str, int, int, int]]) -> None:
        """rows: (order ref, customer, due = this many days after the shipment's promised ETA, qty, penalty in rupees)"""
        rejected = self.import_rows("orders", [
            {"order_ref": ref, "customer": cust, "order_date": self.today.isoformat(), "due_date": self._due(ship_ref, off),
             "sku": sku, "warehouse": wh, "qty": qty, "sla_penalty": pen} for ref, cust, off, qty, pen in rows])
        assert not rejected, rejected

    def event(self, ref: str, kind: str, *, delay_days: int | None = None, received: list[tuple[str, int]] | None = None,
              reason: str | None = None, carrier: str | None = None, seq: int | None = None,
              at: datetime | None = None) -> str:
        info = self.ship_info(ref)
        last_seq = info[2] if info else 0
        ev = CarrierEvent(
            carrier=carrier or (info[0] if info else "RoadRunner Freight"), shipment_ref=ref, event_type=kind,
            seq=seq if seq is not None else last_seq + 1, occurred_at=at or self.now, reason=reason,
            new_eta=info[1] + timedelta(days=delay_days) if delay_days is not None and info else None,
            received=[ReceivedLine(sku=s, qty=q) for s, q in received] if received else None)
        self.sent[ref] = ev
        return self.deliver(ev)

    def approver(self, plan: PlanRef) -> Role:
        return Role.MANAGER if plan.type in MANAGER_APPROVES else Role.PROCUREMENT

    def executor(self, plan: PlanRef) -> Role:
        return Role.OPERATOR if plan.type in MANAGER_APPROVES else Role.ANALYST

    def propose(self, plan: PlanRef) -> PlanRef:
        return self._must(Role.ANALYST, "propose", plan)

    def approve(self, plan: PlanRef) -> PlanRef:
        return self._must(self.approver(plan), "approve", plan)

    def execute(self, plan: PlanRef) -> PlanRef:
        return self._must(self.executor(plan), "execute", plan)

    def reject(self, plan: PlanRef, reason: str) -> PlanRef:
        return self._must(self.approver(plan), "reject", plan, reason=reason)

    def _must(self, role: Role, action: str, plan: PlanRef, **body) -> PlanRef:
        out = self.act_on(role, action, plan, **body)
        assert out is not None, f"{action} on plan {plan.id} was refused"
        plan.version, plan.params = out.version, out.params  # the caller's handle stays current for the next step
        return out

    @staticmethod
    def nudge(plan: PlanRef) -> dict | None:
        """A small, valid edit to the plan's own numbers, or None when it has none to change (a split)."""
        p = plan.params
        if plan.type == PlanType.EXPEDITE:
            return {"days_saved": p["days_saved"] - 1} if p.get("days_saved", 0) > 1 else None
        return {"qty": p["qty"] - 10} if plan.type in (PlanType.REALLOCATE, PlanType.ALT_SUPPLIER) and p.get("qty", 0) > 10 else None

    def blocked_attempts(self, plan: PlanRef) -> None:
        """Two refusals on one proposed plan: a role without approval rights, then the reviewer who edited it."""
        self.act_on(Role.ANALYST, "approve", plan)
        reviewer, change = self.approver(plan), self.nudge(plan)
        if change:
            self.act_on(reviewer, "modify", plan, changes=change)
            self.act_on(reviewer, "approve", self.plan(plan.id))

    def modify_then_approve(self, plan: PlanRef) -> PlanRef:
        """The other reviewer trims the plan first (a modifier may not approve), then the usual approver signs it off."""
        change = self.nudge(plan)
        if change:
            self._must(Role.PROCUREMENT if self.approver(plan) == Role.MANAGER else Role.MANAGER, "modify", plan, changes=change)
        return self.approve(plan)


class DbShowcase(Showcase):
    """Straight into the local database, through the same service functions the routes call."""

    def __init__(self, db: Session):
        super().__init__()
        self.db = db
        self.who = {r: db.execute(select(User).where(User.email == e)).scalar_one() for r, e in ROLE_EMAIL.items()}

    def ship_info(self, ref):
        ship = self.db.execute(select(Shipment).where(Shipment.ref == ref)).scalar_one_or_none()
        return (ship.carrier, ship.promised_eta, ship.last_seq) if ship else None

    def import_rows(self, entity, rows, *, filename=None):
        _, errors = run_import(self.db, entity=entity, rows=list(enumerate(rows, start=1)),
                               source="csv" if filename else "json", filename=filename, user_id=self.who[Role.ANALYST].id)
        run_detection(self.db)
        return [{"row_no": e.row_no, "reason": e.reason} for e in errors]

    def deliver(self, ev):
        result = process_event(self.db, ev)
        if result.outcome == "applied":
            run_detection(self.db)
        return result.outcome

    def disruption(self, wh, sku):
        d = self.db.execute(
            select(Disruption).join(Warehouse, Warehouse.id == Disruption.warehouse_id).join(Sku, Sku.id == Disruption.sku_id)
            .where(Warehouse.name == wh, Sku.code == sku, Disruption.status == "active")).scalar_one()
        return DisruptionRef(d.id)

    def _ref(self, p: Plan) -> PlanRef:
        return PlanRef(p.id, p.type, p.version, p.params_json)

    def draft(self, d, *prefer):
        plans = sorted((p for p in self.db.execute(select(Plan).where(Plan.disruption_id == d.id,
                        Plan.status == PlanStatus.DRAFT)).scalars() if p.metrics_json.get("feasible")),
                       key=lambda p: p.metrics_json.get("rank", 99))
        assert plans, f"no feasible draft for disruption {d.id}"
        return self._ref(next((p for p in plans if p.type in prefer), plans[0]))

    def plan(self, plan_id):
        p = self.db.get(Plan, plan_id)
        self.db.refresh(p)
        return self._ref(p)

    def act_on(self, role, action, plan, **body):
        user = self.who[role]
        args = {"propose": (), "approve": (), "execute": (), "reject": (body.get("reason"),),
                "modify": (body.get("changes"),)}[action]
        try:
            return self._ref(getattr(act, action)(self.db, user, plan.id, plan.version, *args))
        except (Forbidden, Conflict, Invalid, NotFound):
            self.db.flush()  # the refusal's audit row was written before the error was raised
            return None

    def contract_upload(self, customer, filename, lines):
        cid = self.db.execute(select(Customer.id).where(Customer.name == customer)).scalar_one()
        row = contracts.upload(self.db, self.who[Role.ANALYST], cid, filename, make_pdf(lines))
        return row.id, row.terms_json

    def contract_decide(self, contract_id, action, terms=None):
        manager = self.who[Role.MANAGER]
        if action == "confirm":
            contracts.confirm(self.db, manager, contract_id, Terms(**terms), False)
        else:
            contracts.reject(self.db, manager, contract_id)
        self.db.flush()

    def tidy_inbox(self):
        """An inbox that looks lived in: everything but each person's newest few is already read."""
        for uid in self.db.execute(select(User.id)).scalars():
            keep = self.db.execute(select(Notification.id).where(Notification.user_id == uid)
                                   .order_by(Notification.id.desc()).limit(5)).scalars().all()
            self.db.execute(update(Notification).where(Notification.user_id == uid, Notification.id.not_in(keep),
                                                       Notification.read_at.is_(None)).values(read_at=self.now))
        self.db.flush()


class ApiShowcase(Showcase):
    """Through a running API, like the scenarios: signed carrier webhooks, the import endpoints, the plan endpoints."""

    def __init__(self, base_url: str, password: str, webhook_secret: str, base_date: date):
        super().__init__()
        from app.synth.generator import generate

        self.http = httpx.Client(base_url=base_url.rstrip("/"), timeout=180)
        self.password, self.secret = password, webhook_secret
        self.tokens: dict[Role, str] = {}
        self.ships = {s["ref"]: (s["carrier"], s["promised_eta"]) for s in generate(42, base_date)["shipments"]}
        self.seq: dict[str, int] = {}

    def _token(self, role: Role) -> dict:
        if role not in self.tokens:
            r = self.http.post("/auth/login", json={"email": ROLE_EMAIL[role], "password": self.password})
            r.raise_for_status()
            self.tokens[role] = r.json()["access_token"]
        return {"Authorization": f"Bearer {self.tokens[role]}"}

    def ship_info(self, ref):
        return (*self.ships[ref], self.seq.get(ref, 0)) if ref in self.ships else None

    def import_rows(self, entity, rows, *, filename=None):
        h = self._token(Role.ANALYST)
        if filename:
            cols = list(dict.fromkeys(k for r in rows for k in r))
            buf = io.StringIO()
            w = csv.DictWriter(buf, fieldnames=cols)
            w.writeheader()
            w.writerows(rows)
            r = self.http.post("/import/csv", params={"entity": entity}, headers=h,
                               files={"file": (filename, buf.getvalue().encode(), "text/csv")})
        else:
            r = self.http.post("/import/json", headers=h, json={"entity": entity, "rows": rows})
        r.raise_for_status()
        if entity == "shipments":
            for row in rows:
                promised = datetime.fromisoformat(row["promised_eta"])
                self.ships[row["shipment_ref"]] = (row["carrier"], promised if promised.tzinfo else promised.replace(tzinfo=timezone.utc))
        return r.json()["errors"]

    def deliver(self, ev):
        body = json.dumps(ev.model_dump(mode="json", exclude_none=True)).encode()
        r = self.http.post("/webhooks/carrier", content=body,
                           headers={"Content-Type": "application/json", "X-Signature": sign(body, self.secret)})
        outcome = r.json().get("outcome", "invalid") if r.headers.get("content-type", "").startswith("application/json") else "invalid"
        if outcome == "applied":
            self.seq[ev.shipment_ref] = ev.seq
        return outcome

    def disruption(self, wh, sku):
        rows = self.http.get("/disruptions", params={"state": "active"}, headers=self._token(Role.ANALYST)).json()
        return DisruptionRef(next(d["id"] for d in rows if d["warehouse"] == wh and d["sku_code"] == sku))

    def _ref(self, p: dict) -> PlanRef:
        return PlanRef(p["id"], p["type"], p["version"], p["params"])

    def draft(self, d, *prefer):
        plans = self.http.get(f"/disruptions/{d.id}/plans", headers=self._token(Role.ANALYST)).json()
        plans = sorted((p for p in plans if p["status"] == "DRAFT" and p["feasible"]), key=lambda p: p["metrics"].get("rank", 99))
        assert plans, f"no feasible draft for disruption {d.id}"
        return self._ref(next((p for p in plans if p["type"] in prefer), plans[0]))

    def plan(self, plan_id):
        return self._ref(self.http.get(f"/plans/{plan_id}", headers=self._token(Role.MANAGER)).json())

    def act_on(self, role, action, plan, **body):
        r = self.http.post(f"/plans/{plan.id}/{action}", headers=self._token(role), json={"version": plan.version, **body})
        return self._ref(r.json()) if r.status_code == 200 else None

    def contract_upload(self, customer, filename, lines):
        customers = self.http.get("/contracts/customers", headers=self._token(Role.ANALYST)).json()
        cid = next(c["id"] for c in customers if c["name"] == customer)
        r = self.http.post("/contracts/upload", headers=self._token(Role.ANALYST), data={"customer_id": cid},
                           files={"file": (filename, make_pdf(lines), "application/pdf")})
        r.raise_for_status()
        return r.json()["id"], r.json()["terms"]

    def contract_decide(self, contract_id, action, terms=None):
        h = self._token(Role.MANAGER)
        r = (self.http.post(f"/contracts/{contract_id}/confirm", headers=h, json={"terms": terms, "override_ai": False})
             if action == "confirm" else self.http.post(f"/contracts/{contract_id}/reject", headers=h))
        r.raise_for_status()

    def already_loaded(self) -> bool:
        batches = self.http.get("/import/batches", params={"limit": 100}, headers=self._token(Role.ANALYST)).json()
        return any(b["filename"] == MARKER_FILE for b in batches)

    def extras_loaded(self) -> bool:
        return any(c["filename"] == EXTRA_CONTRACT for c in self.http.get("/contracts", headers=self._token(Role.MANAGER)).json())

    def summary(self) -> list[str]:
        h = self._token(Role.MANAGER)
        out = []
        for d in self.http.get("/disruptions", params={"state": "all"}, headers=h).json():
            plans = self.http.get(f"/disruptions/{d['id']}/plans", headers=h).json()
            out.append(f"DIS-{d['id']} {d['warehouse']:<10} {d['sku_code']} {d['type']:<15} {d['severity']:<6} {d['status']:<9} "
                       + " ".join(f"{p['type']}:{p['status']}" for p in plans if p["status"] != "DRAFT"))
        return out


def episodes(s: Showcase) -> None:
    # the dashboard opens on the newest disruption, so the quiet early warning goes in first and a busy one last

    # 0. Mumbai: a carrier that has gone quiet, an early warning with no order at risk yet
    s.event("SHP-1099", "in_transit", at=s.now - timedelta(days=3), reason="Last scan at the Nagpur hub")

    # 1. Mumbai: a Southern Packaging truck slips six days, a plan is proposed and challenged, then the load arrives
    #    after all. The disruption resolves on its own and the plan awaiting approval goes STALE.
    s.orders("Mumbai", "SKU-019", "SHP-1036", [
        ("SHW-M01", "Konkan Fabricators", -2, 80, 14000), ("SHW-M02", "Western Grid Industries", 2, 85, 9000),
        ("SHW-M03", "Thane Hardware Mart", 3, 40, 3000)])
    s.event("SHP-1036", "delayed", delay_days=6, reason="Rail wagon shortage at the Nagpur yard")
    plan = s.propose(s.draft(s.disruption("Mumbai", "SKU-019"), PlanType.REALLOCATE, PlanType.EXPEDITE))
    s.blocked_attempts(plan)
    s.event("SHP-1036", "delivered", reason="Wagon released; arrived with the next train")

    # 2. Chennai: a new inbound shipment is late, and the plan runs the whole way: proposed, approved by the manager,
    #    executed by the Chennai operator
    s.import_rows("shipments", [{"shipment_ref": "SHP-7001", "supplier": "Metro Components", "carrier": "SeaLink Logistics",
                                 "dest_warehouse": "Chennai", "promised_eta": (s.now + timedelta(days=4)).isoformat(),
                                 "sku": "SKU-009", "qty": 150}], filename="inbound_chennai_week44.csv")
    s.orders("Chennai", "SKU-009", "SHP-7001", [
        ("SHW-C01", "Marina Engineering Works", 2, 120, 20000), ("SHW-C02", "Adyar Packaging Co", 6, 90, 4000)])
    s.event("SHP-7001", "delayed", delay_days=9, reason="Vessel omitted the Chennai call; cargo moved to the next sailing")
    plan = s.propose(s.draft(s.disruption("Chennai", "SKU-009"), PlanType.REALLOCATE, PlanType.SPLIT))
    s.approve(plan)
    s.execute(plan)
    s.event("SHP-7001", "delivered", reason="Cargo discharged and gated in")  # the stock it was waiting for lands

    # 2b. Chennai again: another late inbound, this plan approved by the manager and now waiting for the Chennai operator
    s.import_rows("shipments", [{"shipment_ref": "SHP-7003", "supplier": "Metro Components", "carrier": "SeaLink Logistics",
                                 "dest_warehouse": "Chennai", "promised_eta": (s.now + timedelta(days=3)).isoformat(),
                                 "sku": "SKU-005", "qty": 120}], filename="inbound_chennai_week44b.csv")
    s.orders("Chennai", "SKU-005", "SHP-7003", [
        ("SHW-C11", "Marina Engineering Works", 3, 200, 9000), ("SHW-C12", "Adyar Packaging Co", 5, 100, 5000)])
    s.event("SHP-7003", "delayed", delay_days=8, reason="Berth congestion at Ennore; discharge pushed back")
    plan = s.propose(s.draft(s.disruption("Chennai", "SKU-005"), PlanType.REALLOCATE, PlanType.SPLIT))
    s.approve(plan)

    # 3. Bengaluru: Northline Metals is eight days late with an order that is due; the plan waits for approval
    s.orders("Bengaluru", "SKU-013", "SHP-1058", [
        ("SHW-B11", "Lalbagh Electronics", 2, 95, 11000), ("SHW-B12", "Whitefield Tools", 4, 90, 6000),
        ("SHW-B13", "Kaveri Appliances", 5, 60, 16000)])
    s.event("SHP-1058", "delayed", delay_days=8, reason="Driver shortage on the Hosur road; truck re-scheduled")
    s.propose(s.draft(s.disruption("Bengaluru", "SKU-013"), PlanType.ALT_SUPPLIER, PlanType.EXPEDITE))

    # 4. Bengaluru: a newly stocked item with a late shipment; the plan is approved, confirmed, and it works out
    s.import_rows("inventory", [{"warehouse": "Bengaluru", "sku": "SKU-017", "on_hand": 30, "safety_stock": 10}],
                  filename="bengaluru_stock_oct.csv")
    s.orders("Bengaluru", "SKU-017", "SHP-1030", [
        ("SHW-B21", "Sundaram Auto Parts", 1, 140, 18000), ("SHW-B22", "Kaveri Appliances", 3, 110, 12000)])
    s.event("SHP-1030", "delayed", delay_days=7, reason="Consignment held for documentation at the state border")
    plan = s.propose(s.draft(s.disruption("Bengaluru", "SKU-017"), PlanType.EXPEDITE, PlanType.ALT_SUPPLIER))
    s.approve(plan)
    s.execute(plan)

    # 5. Delhi: a delayed Southern Packaging load; the plan is approved and waits for the person who confirms execution
    s.orders("Delhi", "SKU-018", "SHP-1084", [
        ("SHW-D01", "Okhla Precision Parts", 2, 100, 18000), ("SHW-D02", "Gurgaon Retail Supplies", 5, 70, 7000)])
    s.event("SHP-1084", "delayed", delay_days=7, reason="Sea freight transhipment missed at Mundra")
    plan = s.propose(s.draft(s.disruption("Delhi", "SKU-018"), PlanType.EXPEDITE, PlanType.ALT_SUPPLIER))
    s.approve(plan)

    # 6. Delhi: a stock count finds far less than the book said; a transfer is proposed and waits for the manager
    s.import_rows("orders", [{"order_ref": "SHW-D21", "customer": "Okhla Precision Parts", "order_date": s.today.isoformat(),
                              "due_date": (s.today + timedelta(days=6)).isoformat(), "sku": "SKU-012", "warehouse": "Delhi",
                              "qty": 20, "sla_penalty": 15000}])
    s.import_rows("inventory", [{"warehouse": "Delhi", "sku": "SKU-012", "on_hand": 14}], filename="delhi_cycle_count.csv")
    s.propose(s.draft(s.disruption("Delhi", "SKU-012"), PlanType.REALLOCATE))

    # 7. Delhi: the supplier ships only part of an order. The manager declines the first plan.
    s.orders("Delhi", "SKU-016", "SHP-1079", [
        ("SHW-D11", "Yamuna Switchgear", 2, 230, 12000), ("SHW-D12", "Gurgaon Retail Supplies", 6, 230, 5000)])
    s.event("SHP-1079", "partial_delivery", received=[("SKU-016", 90)], delay_days=8,
            reason="Supplier shipped 38% of the purchase order; balance rescheduled")
    plan = s.propose(s.draft(s.disruption("Delhi", "SKU-016"), PlanType.REALLOCATE, PlanType.ALT_SUPPLIER))
    s.reject(plan, "The cost is out of proportion to the penalty at stake; wait for the balance of the shipment.")

    # 8. things that are refused or ignored, all of which leave a trace
    first = s.sent["SHP-1058"]
    s.event("SHP-1058", "delayed", delay_days=8, reason="resent by the carrier", seq=first.seq, at=first.occurred_at)  # duplicate
    s.event("SHP-1030", "in_transit", seq=1)  # out of order
    s.event("SHP-9999", "exception", seq=1, reason="Cargo reported damaged")  # unknown shipment
    s.event("SHP-1062", "in_transit", carrier="SeaLink Logistics")  # wrong carrier for that shipment
    s.import_rows("orders", [
        {"order_ref": "SHW-X01", "customer": "Gurgaon Retail Supplies", "order_date": s.today.isoformat(),
         "due_date": (s.today + timedelta(days=12)).isoformat(), "sku": "SKU-004", "warehouse": "Delhi", "qty": 30,
         "sla_penalty": 2500},
        {"order_ref": "SHW-X02", "customer": "Marina Engineering Works", "order_date": s.today.isoformat(),
         "due_date": (s.today + timedelta(days=9)).isoformat(), "sku": "SKU-999", "warehouse": "Chennai", "qty": 20},
        {"order_ref": "SHW-X03", "customer": "Whitefield Tools", "order_date": s.today.isoformat(),
         "due_date": (s.today - timedelta(days=2)).isoformat(), "sku": "SKU-003", "warehouse": "Bengaluru", "qty": 15},
        {"order_ref": "SHW-X04", "customer": "Unknown Traders", "order_date": s.today.isoformat(),
         "due_date": (s.today + timedelta(days=7)).isoformat(), "sku": "SKU-005", "warehouse": "Mumbai", "qty": 10},
        {"order_ref": "SHW-M01", "customer": "Konkan Fabricators", "order_date": s.today.isoformat(),
         "due_date": (s.today + timedelta(days=7)).isoformat(), "sku": "SKU-002", "warehouse": "Mumbai", "qty": 5},
    ], filename=MARKER_FILE)
    s.import_rows("shipments", [
        {"shipment_ref": "SHP-7002", "supplier": "Himalaya Exports", "carrier": "AirSwift Cargo", "dest_warehouse": "Delhi",
         "promised_eta": (s.now + timedelta(days=5)).isoformat(), "sku": "SKU-004", "qty": 60}],
        filename="inbound_delhi_week44.csv")

    s.tidy_inbox()



# (customer, file, lines, what the manager does: "confirm", "reject", or None = left pending, edits made before confirming)
CONTRACT_SET: list[tuple[str, str, list[str], str | None, dict]] = [
    ("Sundaram Auto Parts", EXTRA_CONTRACT, [
        "SUPPLY AGREEMENT 2025 - Sundaram Auto Parts",
        "1. Scope. The Supplier delivers goods to the Customer's nominated warehouse by the agreed date.",
        "2. Late delivery. Liquidated damages accrue at the rate of 1% of the order value per day of delay,",
        "capped at 5% of the order value.",
        "3. No penalty applies for a delay within a grace period of 2 days.",
        "4. Neither party is liable for delay caused by events of force majeure."], "confirm", {}),
    ("Sundaram Auto Parts", "sundaram_supply_agreement_2026.pdf", CONTRACT_LINES, "confirm", {}),  # replaces the 2025 one
    ("Marina Engineering Works", "marina_master_supply_agreement.pdf", [
        "MASTER SUPPLY AGREEMENT - Marina Engineering Works",
        "1. Scope. Goods are delivered to the Customer's Chennai warehouse by the due date of each order.",
        "2. Late delivery. If an order is late, the Supplier shall pay a penalty of 2.5% of the order value per day",
        "of delay, capped at 12% of the order value.",
        "3. No penalty applies for a delay within a grace period of 2 days.",
        "4. The Customer may terminate an order if the delay exceeds 10 calendar days.",
        "5. Neither party is liable for delay caused by events of force majeure."], "confirm", {}),
    ("Okhla Precision Parts", "okhla_service_level_terms.pdf", [
        "SERVICE LEVEL TERMS - Okhla Precision Parts",
        "1. Scope. Parts are delivered to the Customer's Delhi warehouse by the date on each order.",
        "2. Late delivery. Liquidated damages of Rs. 18,000 per late order are payable by the Supplier,",
        "not to exceed Rs. 40,000 for any one order.",
        "3. The Customer may terminate an order if the delay exceeds 21 calendar days."], "confirm", {"grace_days": 1}),
    ("Lalbagh Electronics", "lalbagh_purchase_terms.pdf", [
        "PURCHASE TERMS - Lalbagh Electronics",
        "1. Scope. Components are delivered to the Customer's Bengaluru warehouse by the order due date.",
        "2. Late delivery. A penalty of 1.5% of the order value per day of delay applies, not exceeding 8% of",
        "the order value.",
        "3. No penalty applies for a delay within a grace period of 4 days.",
        "4. Neither party is liable for delay caused by events of force majeure."], None, {}),
    ("Kaveri Appliances", "kaveri_framework_agreement.pdf", [
        "FRAMEWORK AGREEMENT - Kaveri Appliances",
        "1. Scope. The Supplier delivers appliance components to the Customer's Bengaluru warehouse.",
        "2. Late delivery. Liquidated damages of 1.5% of the order value shall be charged for each day of delay.",
        "3. The Customer may terminate an order if the delay exceeds 15 calendar days."], None, {}),
    ("Whitefield Tools", "whitefield_services_agreement.pdf", [
        "SERVICES AGREEMENT - Whitefield Tools",
        "1. Scope. The Supplier delivers tooling to the Customer's Bengaluru warehouse.",
        "2. Delivery dates on each order are targets agreed between the parties and may be revised by consent.",
        "3. Payment is due 30 days after receipt of goods."], None, {}),
    ("Western Grid Industries", "western_grid_export_contract.pdf", [
        "EXPORT SUPPLY CONTRACT - Western Grid Industries",
        "1. Scope. Goods are supplied to the Customer's Mumbai warehouse.",
        "2. Late delivery. Liquidated damages of USD 500 per late order apply, not to exceed USD 2,000.",
        "3. Either party may refer disputes to arbitration."], "reject", {}),
]


def contract_episodes(s: Showcase) -> None:
    """Contracts in every state a person can find them: confirmed, replaced by a newer one, waiting, and rejected.
    The analyst uploads and the manager decides; the reader's proposals are used as they came, except where the manager edits."""
    for customer, filename, lines, decision, edits in CONTRACT_SET:
        contract_id, terms = s.contract_upload(customer, filename, lines)
        if decision == "confirm":
            s.contract_decide(contract_id, "confirm", terms | edits)
        elif decision == "reject":
            s.contract_decide(contract_id, "reject")


def approval_episodes(s: Showcase) -> None:
    """More plans waiting in each person's queue, two edited by the other reviewer first, one declined, one finished."""
    def inbound(ref: str, supplier: str, carrier: str, wh: str, sku: str, qty: int, days: int) -> None:
        s.import_rows("shipments", [{"shipment_ref": ref, "supplier": supplier, "carrier": carrier, "dest_warehouse": wh,
                                     "promised_eta": (s.now + timedelta(days=days)).isoformat(), "sku": sku, "qty": qty}],
                      filename=f"inbound_{wh.lower()}_{ref.lower()}.csv")

    # Chennai: a reallocation waits for the manager
    inbound("SHP-7101", "Coastal Polymers", "RoadRunner Freight", "Chennai", "SKU-008", 100, 3)
    s.orders("Chennai", "SKU-008", "SHP-7101", [
        (EXTRA_ORDER, "Marina Engineering Works", 2, 90, 16000), ("SHW-A02", "Adyar Packaging Co", 5, 80, 6000)])
    s.event("SHP-7101", "delayed", delay_days=7, reason="Lorry breakdown near Krishnagiri; load moved to another vehicle")
    s.propose(s.draft(s.disruption("Chennai", "SKU-008"), PlanType.REALLOCATE))

    # Mumbai: an expedite is trimmed by the manager, approved by procurement and carried out by the analyst
    inbound("SHP-7102", "Apex Electricals", "AirSwift Cargo", "Mumbai", "SKU-008", 150, 3)
    s.orders("Mumbai", "SKU-008", "SHP-7102", [
        ("SHW-A11", "Konkan Fabricators", 2, 120, 15000), ("SHW-A12", "Western Grid Industries", 5, 100, 8000)])
    s.event("SHP-7102", "delayed", delay_days=6, reason="Customs inspection hold at Nhava Sheva")
    plan = s.propose(s.draft(s.disruption("Mumbai", "SKU-008"), PlanType.EXPEDITE, PlanType.ALT_SUPPLIER))
    s.modify_then_approve(plan)
    s.execute(plan)

    # Delhi: a second supplier is suggested and waits for procurement
    inbound("SHP-7103", "Deccan Plastics", "SeaLink Logistics", "Delhi", "SKU-020", 120, 4)
    s.orders("Delhi", "SKU-020", "SHP-7103", [
        ("SHW-A21", "Okhla Precision Parts", 3, 110, 14000), ("SHW-A22", "Gurgaon Retail Supplies", 6, 100, 7000)])
    s.event("SHP-7103", "delayed", delay_days=8, reason="Port strike at Mundra; vessel held at anchorage")
    s.propose(s.draft(s.disruption("Delhi", "SKU-020"), PlanType.ALT_SUPPLIER, PlanType.EXPEDITE))

    # Chennai: procurement trims a reallocation, the manager approves it, and it waits for the Chennai operator
    inbound("SHP-7104", "Coastal Polymers", "RoadRunner Freight", "Chennai", "SKU-003", 120, 3)
    s.orders("Chennai", "SKU-003", "SHP-7104", [
        ("SHW-A31", "Adyar Packaging Co", 2, 100, 9000), ("SHW-A32", "Marina Engineering Works", 5, 90, 12000)])
    s.event("SHP-7104", "delayed", delay_days=8, reason="Truck diverted after a bridge closure on NH44")
    s.modify_then_approve(s.propose(s.draft(s.disruption("Chennai", "SKU-003"), PlanType.REALLOCATE)))

    # Bengaluru: procurement declines an expedite whose premium outweighs the penalty
    inbound("SHP-7105", "Apex Electricals", "AirSwift Cargo", "Bengaluru", "SKU-014", 150, 4)
    s.orders("Bengaluru", "SKU-014", "SHP-7105", [
        ("SHW-A41", "Lalbagh Electronics", 3, 130, 11000), ("SHW-A42", "Whitefield Tools", 6, 120, 5000)])
    s.event("SHP-7105", "delayed", delay_days=7, reason="Aircraft swap at Delhi; cargo offloaded")
    plan = s.propose(s.draft(s.disruption("Bengaluru", "SKU-014"), PlanType.EXPEDITE, PlanType.ALT_SUPPLIER))
    s.reject(plan, "The freight premium is higher than the penalty at stake; the supplier has confirmed a new date.")

    # Mumbai: another reallocation waits for the manager
    inbound("SHP-7106", "Northline Metals", "RoadRunner Freight", "Mumbai", "SKU-001", 120, 3)
    s.orders("Mumbai", "SKU-001", "SHP-7106", [
        ("SHW-A51", "Thane Hardware Mart", 3, 150, 6000), ("SHW-A52", "Konkan Fabricators", 6, 110, 9000)])
    s.event("SHP-7106", "delayed", delay_days=9, reason="Loading delayed at the supplier's plant")
    s.propose(s.draft(s.disruption("Mumbai", "SKU-001"), PlanType.REALLOCATE, PlanType.SPLIT))


def extras(s: Showcase) -> None:
    """Contracts first, so the penalties on the new orders already follow them, then the extra approvals."""
    contract_episodes(s)
    approval_episodes(s)
    s.tidy_inbox()


def seed(db: Session, *, only_extras: bool = False) -> Showcase:
    s = DbShowcase(db)
    if not only_extras:
        episodes(s)
    extras(s)
    return s


def summary(db: Session) -> list[str]:
    wh = {w.id: w.name for w in db.execute(select(Warehouse)).scalars()}
    sku = {k.id: k.code for k in db.execute(select(Sku)).scalars()}
    lines = []
    for d in db.execute(select(Disruption).order_by(Disruption.id)).scalars():
        plans = db.execute(select(Plan).where(Plan.disruption_id == d.id).order_by(Plan.id)).scalars().all()
        lines.append(f"DIS-{d.id} {wh[d.warehouse_id]:<10} {sku[d.sku_id]} {d.type:<15} {d.severity:<6} {d.status:<9} "
                     + " ".join(f"{p.type}:{p.status}" for p in plans if p.status != PlanStatus.DRAFT)
                     + f" (+{sum(p.status == PlanStatus.DRAFT for p in plans)} draft)")
    return lines


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true", help="local database only: run everything, print, roll back")
    ap.add_argument("--extra", action="store_true",
                    help="only add the contracts and the extra plans, to data that already holds the showcase")
    ap.add_argument("--api", help="base URL of a running API; use it instead of the local database")
    ap.add_argument("--password", default=DEMO_PASSWORD, help="the demo users' password (with --api)")
    ap.add_argument("--webhook-secret", default=settings.webhook_secret, help="the API's WEBHOOK_SECRET (with --api)")
    ap.add_argument("--base-date", type=date.fromisoformat, default=date.today(),
                    help="the date the base data was generated for (with --api; the day it was loaded)")
    args = ap.parse_args()

    if args.api:
        s = ApiShowcase(args.api, args.password, args.webhook_secret, args.base_date)
        if s.extras_loaded() or (s.already_loaded() and not args.extra):
            print("The showcase data is already loaded.")
            return 1
        if not args.extra:
            episodes(s)
        extras(s)
        print("\n".join(s.summary()))
        print("showcase data loaded through", args.api)
        return 0

    with SessionLocal() as db:
        loaded = lambda ref: db.execute(select(func.count(Order.id)).where(Order.ref == ref)).scalar_one()  # noqa: E731
        if loaded(EXTRA_ORDER) or (loaded(MARKER_ORDER) and not args.extra):
            print("The showcase data is already loaded.")
            return 1
        seed(db, only_extras=args.extra)
        print("\n".join(summary(db)))
        print("carrier events:", dict(db.execute(select(ShipmentEvent.outcome, func.count()).group_by(ShipmentEvent.outcome)).all()))
        if args.dry_run:
            db.rollback()
            print("dry run: rolled back")
        else:
            db.commit()
            print("showcase data loaded")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
