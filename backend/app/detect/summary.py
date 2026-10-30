"""Plain-language disruption summary built from computed facts only (the AI layer may rephrase it later)."""
from datetime import date


def _d(x: date | None) -> str:
    return f"{x.day} {x.strftime('%b')}" if x else "unknown"


def _plural(n: int, word: str) -> str:
    return f"{n} {word}" if n == 1 else f"{n} {word}s"


def template_summary(*, dtype: str, warehouse: str, sku: str, shipment_ref: str | None, supplier: str | None,
                     delay_days: int, promised: date | None, current: date | None, n_at_risk: int, n_newly: int,
                     n_high: int, penalty_exposure: float) -> str:
    if dtype == "late_shipment":
        lead = (f"Shipment {shipment_ref} from {supplier} to {warehouse} is {_plural(delay_days, 'day')} late "
                f"(promised {_d(promised)}, now {_d(current)}).")
    elif dtype == "supplier_delay":
        lead = (f"{supplier} delivered less than ordered on shipment {shipment_ref} to {warehouse}; "
                f"the balance is expected {_d(current)} (promised {_d(promised)}).")
    else:
        lead = f"Projected stock of {sku} at {warehouse} cannot cover the open orders in time."
    if n_at_risk == 0:
        return f"{lead} No customer order is at risk yet."
    parts = [lead, f"{_plural(n_at_risk, 'order')} at risk"]
    if n_newly:
        parts[-1] += f", {n_newly} of them newly at risk because of this event"
    parts[-1] += "."
    if n_high:
        parts.append(f"{n_high} rated high risk.")
    if penalty_exposure > 0:
        parts.append(f"SLA penalties at stake: {penalty_exposure:,.0f}.")
    return " ".join(parts)
