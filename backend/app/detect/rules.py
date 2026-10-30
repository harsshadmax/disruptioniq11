"""Detection rules (blueprint 7.1). Pure functions that return the reasons a rule fired (empty list = no)."""
from datetime import datetime
from typing import Sequence

OPEN_STATUSES = ("in_transit", "delayed", "partially_received", "exception")
DEFAULT_SCAN_GAP_HOURS = 12.0  # typical gap between carrier scans on a route
SUPPLIER_LATE_SHIPMENTS = 2
LEAD_TIME_FACTOR = 1.25


def delay_days(promised_eta: datetime, current_eta: datetime) -> int:
    return max(0, (current_eta - promised_eta).days)


def late_shipment_reasons(*, status: str, promised_eta: datetime, current_eta: datetime, last_scan_at: datetime | None,
                          now: datetime, median_scan_gap_hours: float = DEFAULT_SCAN_GAP_HOURS) -> list[str]:
    if status == "delivered":
        return []
    reasons = []
    if current_eta > promised_eta:
        reasons.append(f"ETA moved {delay_days(promised_eta, current_eta)} day(s) past the promise")
    if status == "delayed" and not reasons:
        reasons.append("carrier reports the shipment as delayed")
    if last_scan_at is not None and status in ("in_transit", "delayed"):
        silent = (now - last_scan_at).total_seconds() / 3600
        if silent > 3 * median_scan_gap_hours:
            reasons.append(f"no carrier scan for {silent:.0f} hours (route norm {median_scan_gap_hours:.0f})")
    return reasons


def supplier_delay_reasons(*, partial_receipt: bool, late_open_shipments: int,
                           recent_lead_times: Sequence[float] = (), baseline_lead_days: float = 0) -> list[str]:
    reasons = []
    if partial_receipt:
        reasons.append("supplier delivered less than the quantity ordered")
    if late_open_shipments >= SUPPLIER_LATE_SHIPMENTS:
        reasons.append(f"{late_open_shipments} open shipments from this supplier are late")
    recent = list(recent_lead_times)[-3:]
    if len(recent) == 3 and baseline_lead_days > 0 and sum(recent) / 3 > LEAD_TIME_FACTOR * baseline_lead_days:
        reasons.append("recent lead times are more than 25% above the supplier baseline")
    return reasons


def below_safety_stock(*, on_hand: int, inbound: int, demand: int, safety_stock: int) -> bool:
    """Projected stock after all inbound supply and all open demand is under the safety level."""
    return on_hand + inbound - demand < safety_stock
