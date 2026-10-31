"""Run detection over the whole world and keep `disruptions` / `order_risk` in step with it.

One active disruption per (warehouse, SKU) cell. Its type can escalate (late_shipment -> stock_shortage)
without losing its identity. The type is decided like this:
  at-risk orders exist and demand exceeds even the promised supply   -> stock_shortage
  otherwise a feeding shipment is partially received / supplier is late -> supplier_delay
  otherwise a feeding shipment is late                                 -> late_shipment
  no at-risk orders but projected stock is under safety stock           -> stock_shortage (low)
Disruptions that no longer qualify are resolved. The caller commits.
"""
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy import delete, select, text
from sqlalchemy.orm import Session

from app.audit.service import write_audit
from app.decide.risk import risk_score
from app.detect.rules import below_safety_stock, delay_days, late_shipment_reasons, supplier_delay_reasons
from app.detect.summary import template_summary
from app.enums import DisruptionType
from app.impact.allocation import FULL
from app.impact.service import CellWorld, InboundInfo, analyze, load_world
from app.models import Disruption, OrderRisk, Sku, Warehouse
from app.notify.service import notify, recipients
from app.notify.sla import remind_overdue
from app.options.service import generate_plans, retire_plans

SYSTEM_ROLE = "system"
_DETECTION_LOCK_KEY = 7002  # the audit chain uses 7001


@dataclass
class DetectionReport:
    created: list[int] = field(default_factory=list)
    updated: list[int] = field(default_factory=list)
    resolved: list[int] = field(default_factory=list)
    unchanged: list[int] = field(default_factory=list)

    @property
    def changed(self) -> bool:
        return bool(self.created or self.updated or self.resolved)


@dataclass
class _Desired:
    type: str
    severity: str
    shipment_id: int | None
    summary: str
    risks: list[dict]  # ranked order_risk rows (without disruption id)


def _decide(cell: CellWorld, now: datetime, late_count: dict[int, int]) -> tuple[str, InboundInfo | None] | None:
    a = analyze(cell, now.date())
    at_risk = [k for k, al in a.after.items() if al.status != FULL]
    promised_short = any(al.status != FULL for al in a.before.values())

    def is_late(ib: InboundInfo) -> bool:
        return bool(late_shipment_reasons(status=ib.status, promised_eta=ib.promised_eta, current_eta=ib.current_eta,
                                          last_scan_at=ib.last_scan_at, now=now))

    def is_supplier_issue(ib: InboundInfo) -> bool:
        return bool(supplier_delay_reasons(partial_receipt=ib.qty_received < ib.qty_expected and ib.qty_received > 0,
                                           late_open_shipments=late_count.get(ib.supplier_id, 0)))

    late = sorted((ib for ib in cell.inbound if is_late(ib)), key=lambda ib: -delay_days(ib.promised_eta, ib.current_eta))
    supplier_issue = [ib for ib in cell.inbound if is_supplier_issue(ib)]
    partial = [ib for ib in supplier_issue if ib.qty_received > 0]
    worst = (partial or late or supplier_issue or [None])[0]

    if at_risk:
        if promised_short:
            return DisruptionType.STOCK_SHORTAGE, worst
        if supplier_issue:
            return DisruptionType.SUPPLIER_DELAY, worst
        if late:
            return DisruptionType.LATE_SHIPMENT, worst
        return DisruptionType.STOCK_SHORTAGE, worst
    if supplier_issue and (partial or late):
        return DisruptionType.SUPPLIER_DELAY, worst
    if late:
        return DisruptionType.LATE_SHIPMENT, late[0]
    remaining = sum(ib.qty_expected - ib.qty_received for ib in cell.inbound)
    if below_safety_stock(on_hand=cell.on_hand, inbound=remaining, demand=sum(ln.qty for ln in cell.lines),
                          safety_stock=cell.safety_stock):
        return DisruptionType.STOCK_SHORTAGE, worst
    return None


def _build(cell: CellWorld, now: datetime, dtype: str, trigger: InboundInfo | None, wh_name: str, sku: Sku) -> _Desired:
    a = analyze(cell, now.date())
    by_line = {ln.line_id: ln for ln in cell.lines}
    rows = []
    for lid, al in a.after.items():
        if al.status == FULL:
            continue
        ln = by_line[lid]
        r = risk_score(uncovered_qty=al.uncovered_qty, order_qty=ln.order_qty, slack_days=al.slack_days, tier=ln.tier,
                       sla_penalty=ln.sla_penalty, supplier_reliability=trigger.reliability if trigger else None)
        rows.append({
            "order_id": ln.order_id, "order_ref": ln.order_ref, "score": r.score, "band": r.band, "due": ln.due_date,
            "factors": {
                "factors": r.factors, "newly_at_risk": lid in a.newly_at_risk,
                "status_before": a.before[lid].status, "status_after": al.status,
                "line_qty": ln.qty, "covered_qty": al.covered_qty, "uncovered_qty": al.uncovered_qty,
                "order_qty": ln.order_qty, "slack_days": al.slack_days,
                "earliest_fulfil": al.earliest_fulfil.isoformat() if al.earliest_fulfil else None,
                "sla_penalty": ln.sla_penalty,
            },
        })
    rows.sort(key=lambda r: (-r["score"], r["due"], r["order_id"]))
    for i, r in enumerate(rows, start=1):
        r["rank"] = i
        del r["due"]
    bands = {r["band"] for r in rows}
    severity = "high" if "high" in bands else "medium" if "medium" in bands else "low"
    summary = template_summary(
        dtype=dtype, warehouse=wh_name, sku=sku.code, shipment_ref=trigger.ref if trigger else None,
        supplier=trigger.supplier if trigger else None,
        delay_days=delay_days(trigger.promised_eta, trigger.current_eta) if trigger else 0,
        promised=trigger.promised_eta.date() if trigger else None, current=trigger.current_eta.date() if trigger else None,
        n_at_risk=len(rows), n_newly=sum(1 for r in rows if r["factors"]["newly_at_risk"]),
        n_high=sum(1 for r in rows if r["band"] == "high"),
        penalty_exposure=sum(r["factors"]["sla_penalty"] for r in rows))
    return _Desired(dtype, severity, trigger.shipment_id if trigger else None, summary, rows)


def run_detection(db: Session, now: datetime | None = None) -> DetectionReport:
    now = now or datetime.now(timezone.utc)
    # one detection at a time: two runs that both see "no active disruption" would each create one
    db.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": _DETECTION_LOCK_KEY})
    world = load_world(db)

    # a supplier with several late open shipments is itself a signal (counted once per shipment)
    late_ships: dict[int, set[int]] = {}
    for cell in world.values():
        for ib in cell.inbound:
            if late_shipment_reasons(status=ib.status, promised_eta=ib.promised_eta, current_eta=ib.current_eta,
                                     last_scan_at=ib.last_scan_at, now=now):
                late_ships.setdefault(ib.supplier_id, set()).add(ib.shipment_id)
    late_count = {sid: len(ids) for sid, ids in late_ships.items()}

    wh_names = {w.id: w.name for w in db.execute(select(Warehouse)).scalars()}
    skus = {s.id: s for s in db.execute(select(Sku)).scalars()}
    active = {(d.warehouse_id, d.sku_id): d for d in db.execute(
        select(Disruption).where(Disruption.status == "active")).scalars()}

    report = DetectionReport()
    seen: set[tuple[int, int]] = set()
    for key, cell in sorted(world.items()):
        decision = _decide(cell, now, late_count)
        if decision is None:
            continue
        dtype, trigger = decision
        want = _build(cell, now, dtype, trigger, wh_names[cell.warehouse_id], skus[cell.sku_id])
        seen.add(key)
        d = active.get(key)
        new_rows = [(r["order_id"], r["score"], r["rank"], r["factors"]["sla_penalty"]) for r in want.risks]
        if d is None:
            d = Disruption(type=want.type, shipment_id=want.shipment_id, sku_id=cell.sku_id,
                           warehouse_id=cell.warehouse_id, severity=want.severity, status="active",
                           summary_text=want.summary)
            db.add(d)
            db.flush()
            action = "disruption.detected"
            report.created.append(d.id)
        else:
            old_rows = [(r.order_id, r.score, r.rank, r.factors_json.get("sla_penalty")) for r in db.execute(
                select(OrderRisk).where(OrderRisk.disruption_id == d.id).order_by(OrderRisk.rank)).scalars()]
            if (d.type, d.severity, d.shipment_id, old_rows) == (want.type, want.severity, want.shipment_id, new_rows):
                report.unchanged.append(d.id)
                continue
            d.type, d.severity, d.shipment_id, d.summary_text = want.type, want.severity, want.shipment_id, want.summary
            db.execute(delete(OrderRisk).where(OrderRisk.disruption_id == d.id))
            action = "disruption.updated"
            report.updated.append(d.id)
        db.add_all([OrderRisk(disruption_id=d.id, order_id=r["order_id"], score=r["score"], band=r["band"],
                              factors_json=r["factors"], rank=r["rank"]) for r in want.risks])
        db.flush()
        write_audit(db, actor_id=None, role=SYSTEM_ROLE, action=action, entity_type="disruption", entity_id=d.id,
                    payload={"type": want.type, "severity": want.severity, "warehouse": wh_names[cell.warehouse_id],
                             "sku": skus[cell.sku_id].code, "orders_at_risk": len(want.risks),
                             "newly_at_risk": sum(1 for r in want.risks if r["factors"]["newly_at_risk"])})
        generate_plans(db, d, now, world)
        if action == "disruption.detected":
            notify(db, recipients(db, "plan.create"), "disruption.detected",
                   f"New {want.severity}-severity disruption at {wh_names[cell.warehouse_id]}: {want.summary}",
                   f"disruption:{d.id}")

    for key, d in active.items():
        if key not in seen:
            d.status = "resolved"
            retire_plans(db, d.id, "the disruption is resolved")
            db.flush()
            report.resolved.append(d.id)
            write_audit(db, actor_id=None, role=SYSTEM_ROLE, action="disruption.resolved", entity_type="disruption",
                        entity_id=d.id, reason="no longer detected")
    remind_overdue(db, now)
    return report


def refresh_disruptions(db: Session) -> DetectionReport | None:
    """Detection after an event or import. A detection bug must not lose the event that triggered it."""
    try:
        with db.begin_nested():
            return run_detection(db)
    except Exception:  # noqa: BLE001
        logging.getLogger(__name__).exception("disruption detection failed")
        return None
