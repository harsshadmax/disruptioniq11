"""Earliest-due-date allocation (blueprint 7.2). Pure: no database, no clock.

For one (warehouse, SKU) cell, walk the open demand in due-date order (ties: gold before silver before bronze)
and decide how much of each order the supply can cover in time. Supply is what is on hand today plus each
inbound quantity from the day it arrives. An order needs its stock `handling_days` before the due date.
Run it twice, once with promised ETAs and once with current ETAs, and compare.
"""
from dataclasses import dataclass
from datetime import date, timedelta

TIER_RANK = {"gold": 0, "silver": 1, "bronze": 2}
FULL, PARTIAL, NONE = "full", "partial", "none"


@dataclass(frozen=True)
class Demand:
    key: int  # order line id
    due_date: date
    tier: str
    qty: int


@dataclass(frozen=True)
class Supply:
    arrival: date
    qty: int


@dataclass(frozen=True)
class Allocation:
    key: int
    due_date: date
    qty: int
    covered_qty: int
    earliest_fulfil: date | None  # first day the whole line could be ready to ship; None if supply never reaches it

    @property
    def uncovered_qty(self) -> int:
        return self.qty - self.covered_qty

    @property
    def status(self) -> str:
        if self.covered_qty >= self.qty:
            return FULL
        return PARTIAL if self.covered_qty > 0 else NONE

    @property
    def slack_days(self) -> int | None:
        return None if self.earliest_fulfil is None else (self.due_date - self.earliest_fulfil).days


def allocate(on_hand: int, supply: list[Supply], demands: list[Demand], today: date,
             handling_days: int = 1) -> dict[int, Allocation]:
    events = sorted(((max(s.arrival, today), s.qty) for s in supply if s.qty > 0), key=lambda e: e[0])
    ordered = sorted(demands, key=lambda d: (d.due_date, TIER_RANK.get(d.tier, 9), d.key))

    def available_by(deadline: date) -> int:
        if deadline < today:
            return 0  # nothing can be handled in the past
        return max(on_hand, 0) + sum(q for arrival, q in events if arrival <= deadline)

    def ready_on(total: int) -> date | None:
        if total <= max(on_hand, 0):
            return today
        running = max(on_hand, 0)
        for arrival, q in events:
            running += q
            if running >= total:
                return arrival
        return None

    out: dict[int, Allocation] = {}
    cumulative = 0
    for d in ordered:
        before = cumulative
        cumulative += d.qty
        covered = max(0, min(d.qty, available_by(d.due_date - timedelta(days=handling_days)) - before))
        ready = ready_on(cumulative)
        out[d.key] = Allocation(d.key, d.due_date, d.qty, covered,
                                None if ready is None else ready + timedelta(days=handling_days))
    return out


def newly_at_risk(before: dict[int, Allocation], after: dict[int, Allocation]) -> set[int]:
    """Lines fully covered under the promise but not fully covered now."""
    return {k for k, a in after.items() if a.status != FULL and before.get(k) is not None and before[k].status == FULL}
