"""Showcase data: situations in every city and every plan status, driven through the real services.

  python -m app.synth.showcase              add the showcase situations (needs the base demo data; refuses to run twice)
  python -m app.synth.showcase --dry-run    do everything, print what it would leave behind, then roll back

Nothing is inserted by hand. Orders, stock and shipments come in through the importers, carrier events through the
webhook processor, and plans move through propose / modify / approve / reject / execute as the people who hold those
permissions, so every guard runs and every audit row, notification and disruption is the real thing. The base data
(`python -m app.synth --seed 42`) and the two scripted scenarios (`python -m app.scenarios s1|s2`) are left alone.
"""
import argparse
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.act import service as act
from app.act.errors import Conflict, Forbidden, Invalid, NotFound
from app.detect.service import run_detection
from app.enums import PlanStatus, PlanType, Role
from app.db import SessionLocal
from app.ingest.importers import run_import
from app.ingest.webhook import CarrierEvent, ReceivedLine, process_event
from app.models import (Disruption, Notification, Order, Plan, Shipment, ShipmentEvent, Sku, User, Warehouse)

MARKER_ORDER = "SHW-M01"
MANAGER_APPROVES = {PlanType.REALLOCATE, PlanType.SPLIT}  # the matrix: managers approve and operators execute these
ROLE_EMAIL = {Role.ANALYST: "analyst@diq.test", Role.MANAGER: "manager@diq.test", Role.OPERATOR: "operator@diq.test",
              Role.PROCUREMENT: "procurement@diq.test"}


class Showcase:
    def __init__(self, db: Session):
        self.db = db
        self.now = datetime.now(timezone.utc).replace(second=0, microsecond=0)
        self.today = self.now.date()
        self.who = {r: db.execute(select(User).where(User.email == e)).scalar_one() for r, e in ROLE_EMAIL.items()}
        self.sent: dict[str, CarrierEvent] = {}

    # --- inputs: the same doors the product uses ---------------------------------------------------------------

    def _ship(self, ref: str) -> Shipment:
        return self.db.execute(select(Shipment).where(Shipment.ref == ref)).scalar_one()

    def _due(self, ref: str, days_after_eta: int) -> str:
        eta = self._ship(ref).promised_eta.date()
        return max(eta + timedelta(days=days_after_eta), self.today + timedelta(days=3)).isoformat()

    def import_rows(self, entity: str, rows: list[dict], *, source: str = "json", filename: str | None = None,
                    detect: bool = True):
        batch, errors = run_import(self.db, entity=entity, rows=list(enumerate(rows, start=1)), source=source,
                                   filename=filename, user_id=self.who[Role.ANALYST].id)
        if detect:
            run_detection(self.db)
        return batch, errors

    def orders(self, wh: str, sku: str, ship_ref: str, rows: list[tuple[str, str, int, int, int]]) -> None:
        """rows: (order ref, customer, due = this many days after the shipment's promised ETA, qty, penalty in rupees)"""
        _, errors = self.import_rows("orders", [
            {"order_ref": ref, "customer": cust, "order_date": self.today.isoformat(), "due_date": self._due(ship_ref, off),
             "sku": sku, "warehouse": wh, "qty": qty, "sla_penalty": pen} for ref, cust, off, qty, pen in rows])
        assert not errors, errors

    def event(self, ref: str, kind: str, *, delay_days: int | None = None, received: list[tuple[str, int]] | None = None,
              reason: str | None = None, carrier: str | None = None, seq: int | None = None, detect: bool = True):
        ship = self.db.execute(select(Shipment).where(Shipment.ref == ref)).scalar_one_or_none()
        ev = CarrierEvent(
            carrier=carrier or (ship.carrier if ship else "RoadRunner Freight"), shipment_ref=ref, event_type=kind,
            seq=seq if seq is not None else (ship.last_seq + 1 if ship else 1), occurred_at=self.now, reason=reason,
            new_eta=ship.promised_eta + timedelta(days=delay_days) if delay_days is not None and ship else None,
            received=[ReceivedLine(sku=s, qty=q) for s, q in received] if received else None)
        result = process_event(self.db, ev)
        self.sent[ref] = ev
        if result.outcome == "applied" and detect:
            run_detection(self.db)
        return result

    # --- people moving plans -----------------------------------------------------------------------------------

    def disruption(self, wh: str, sku: str) -> Disruption | None:
        return self.db.execute(
            select(Disruption).join(Warehouse, Warehouse.id == Disruption.warehouse_id).join(Sku, Sku.id == Disruption.sku_id)
            .where(Warehouse.name == wh, Sku.code == sku, Disruption.status == "active")).scalar_one_or_none()

    def draft(self, d: Disruption, *prefer: str) -> Plan:
        plans = sorted((p for p in self.db.execute(select(Plan).where(Plan.disruption_id == d.id,
                        Plan.status == PlanStatus.DRAFT)).scalars() if p.metrics_json.get("feasible")),
                       key=lambda p: p.metrics_json.get("rank", 99))
        assert plans, f"no feasible draft for disruption {d.id}"
        return next((p for p in plans if p.type in prefer), plans[0])

    def approver(self, plan: Plan) -> User:
        return self.who[Role.MANAGER if plan.type in MANAGER_APPROVES else Role.PROCUREMENT]

    def executor(self, plan: Plan) -> User:
        return self.who[Role.OPERATOR if plan.type in MANAGER_APPROVES else Role.ANALYST]

    def attempt(self, fn, *args, **kw) -> None:
        """A request the rules refuse. The service writes its audit row before raising; the session keeps it."""
        try:
            fn(self.db, *args, **kw)
        except (Forbidden, Conflict, Invalid, NotFound):
            pass
        self.db.flush()

    def propose(self, plan: Plan) -> Plan:
        return act.propose(self.db, self.who[Role.ANALYST], plan.id, plan.version)

    def approve(self, plan: Plan) -> Plan:
        return act.approve(self.db, self.approver(plan), plan.id, plan.version)

    def execute(self, plan: Plan) -> Plan:
        return act.execute(self.db, self.executor(plan), plan.id, plan.version)

    def reject(self, plan: Plan, reason: str) -> Plan:
        return act.reject(self.db, self.approver(plan), plan.id, plan.version, reason)

    def blocked_attempts(self, plan: Plan) -> None:
        """Two refusals on one proposed plan: a role without approval rights, then the reviewer who edited it."""
        self.attempt(act.approve, self.who[Role.ANALYST], plan.id, plan.version)
        reviewer, p = self.approver(plan), plan.params_json
        change = ({"qty": p["qty"] - 10} if p.get("qty", 0) > 10 else {"days_saved": p["days_saved"] - 1}
                  if p.get("days_saved", 0) > 1 else None)
        if change:
            self.attempt(act.modify, reviewer, plan.id, plan.version, change)
            self.db.refresh(plan)
            self.attempt(act.approve, reviewer, plan.id, plan.version)


def seed(db: Session) -> "Showcase":
    s = Showcase(db)
    # the dashboard opens on the newest disruption, so the quiet early warning goes in first and a busy one last

    # 0. Mumbai: a carrier that has gone quiet, an early warning with no order at risk yet
    s.db.execute(update(Shipment).where(Shipment.ref == "SHP-1099").values(last_scan_at=s.now - timedelta(days=3)))
    run_detection(s.db)

    # 1. Mumbai: a Southern Packaging truck slips six days, a plan is proposed and challenged, then the load arrives
    #    after all. The disruption resolves on its own and the plan awaiting approval goes STALE.
    s.orders("Mumbai", "SKU-019", "SHP-1036", [
        ("SHW-M01", "Konkan Fabricators", -2, 80, 14000), ("SHW-M02", "Western Grid Industries", 2, 85, 9000),
        ("SHW-M03", "Thane Hardware Mart", 3, 40, 3000)])
    s.event("SHP-1036", "delayed", delay_days=6, reason="Rail wagon shortage at the Nagpur yard")
    d = s.disruption("Mumbai", "SKU-019")
    plan = s.propose(s.draft(d, PlanType.REALLOCATE, PlanType.EXPEDITE))
    s.blocked_attempts(plan)
    s.event("SHP-1036", "delivered", reason="Wagon released; arrived with the next train")

    # 2. Chennai: a new inbound shipment is late, and the plan runs the whole way: proposed, approved by the manager,
    #    executed by the Chennai operator
    s.import_rows("shipments", [{"shipment_ref": "SHP-7001", "supplier": "Metro Components", "carrier": "SeaLink Logistics",
                                 "dest_warehouse": "Chennai", "promised_eta": (s.now + timedelta(days=4)).isoformat(),
                                 "sku": "SKU-009", "qty": 150}], source="csv", filename="inbound_chennai_week44.csv",
                  detect=False)
    s.orders("Chennai", "SKU-009", "SHP-7001", [
        ("SHW-C01", "Marina Engineering Works", 2, 120, 20000), ("SHW-C02", "Adyar Packaging Co", 6, 90, 4000)])
    s.event("SHP-7001", "delayed", delay_days=9, reason="Vessel omitted the Chennai call; cargo moved to the next sailing")
    d = s.disruption("Chennai", "SKU-009")
    plan = s.propose(s.draft(d, PlanType.REALLOCATE, PlanType.SPLIT))
    s.approve(plan)
    s.execute(plan)
    s.event("SHP-7001", "delivered", reason="Cargo discharged and gated in")  # the stock it was waiting for lands

    # 2b. Chennai again: another late inbound, this plan approved by the manager and now waiting for the Chennai operator
    s.import_rows("shipments", [{"shipment_ref": "SHP-7003", "supplier": "Metro Components", "carrier": "SeaLink Logistics",
                                 "dest_warehouse": "Chennai", "promised_eta": (s.now + timedelta(days=3)).isoformat(),
                                 "sku": "SKU-005", "qty": 120}], source="csv", filename="inbound_chennai_week44b.csv",
                  detect=False)
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
                  source="csv", filename="bengaluru_stock_oct.csv", detect=False)
    s.orders("Bengaluru", "SKU-017", "SHP-1030", [
        ("SHW-B21", "Sundaram Auto Parts", 1, 140, 18000), ("SHW-B22", "Kaveri Appliances", 3, 110, 12000)])
    s.event("SHP-1030", "delayed", delay_days=7, reason="Consignment held for documentation at the state border")
    d = s.disruption("Bengaluru", "SKU-017")
    plan = s.propose(s.draft(d, PlanType.EXPEDITE, PlanType.ALT_SUPPLIER))
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
                              "qty": 20, "sla_penalty": 15000}], detect=False)
    s.import_rows("inventory", [{"warehouse": "Delhi", "sku": "SKU-012", "on_hand": 14}],
                  source="csv", filename="delhi_cycle_count.csv")
    s.propose(s.draft(s.disruption("Delhi", "SKU-012"), PlanType.REALLOCATE))

    # 7. Delhi: the supplier ships only part of an order. The manager declines the first plan.
    s.orders("Delhi", "SKU-016", "SHP-1079", [
        ("SHW-D11", "Yamuna Switchgear", 2, 230, 12000), ("SHW-D12", "Gurgaon Retail Supplies", 6, 230, 5000)])
    s.event("SHP-1079", "partial_delivery", received=[("SKU-016", 90)], delay_days=8,
            reason="Supplier shipped 38% of the purchase order; balance rescheduled")
    plan = s.propose(s.draft(s.disruption("Delhi", "SKU-016"), PlanType.REALLOCATE, PlanType.ALT_SUPPLIER))
    s.reject(plan, "The cost is out of proportion to the penalty at stake; wait for the balance of the shipment.")

    # 8. things that are refused or ignored, all of which leave a trace
    s.event("SHP-1058", "delayed", delay_days=8, reason="resent by the carrier", seq=s.sent["SHP-1058"].seq)  # duplicate
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
    ], source="csv", filename="orders_week44.csv")
    s.import_rows("shipments", [
        {"shipment_ref": "SHP-7002", "supplier": "Himalaya Exports", "carrier": "AirSwift Cargo", "dest_warehouse": "Delhi",
         "promised_eta": (s.now + timedelta(days=5)).isoformat(), "sku": "SKU-004", "qty": 60}],
        source="csv", filename="inbound_delhi_week44.csv")

    # 9. an inbox that looks lived in: everything but the newest few is already read
    for uid in db.execute(select(User.id)).scalars():
        keep = db.execute(select(Notification.id).where(Notification.user_id == uid).order_by(Notification.id.desc())
                          .limit(5)).scalars().all()
        db.execute(update(Notification).where(Notification.user_id == uid, Notification.id.not_in(keep),
                                              Notification.read_at.is_(None)).values(read_at=s.now))
    db.flush()
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
    ap.add_argument("--dry-run", action="store_true", help="run everything, print the result, roll back")
    args = ap.parse_args()
    with SessionLocal() as db:
        if db.execute(select(func.count(Order.id)).where(Order.ref == MARKER_ORDER)).scalar_one():
            print("The showcase data is already loaded.")
            return 1
        seed(db)
        print("\n".join(summary(db)))
        events = db.execute(select(ShipmentEvent.outcome, func.count()).group_by(ShipmentEvent.outcome)).all()
        print("carrier events:", dict(events))
        if args.dry_run:
            db.rollback()
            print("dry run: rolled back")
        else:
            db.commit()
            print("showcase data loaded")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
