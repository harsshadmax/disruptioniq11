"""Order risk score, 0 to 100, with the contribution of every factor (blueprint 7.3). Pure."""
from dataclasses import dataclass

WEIGHTS = {"shortfall": 0.30, "time": 0.25, "tier": 0.20, "penalty": 0.15, "supplier": 0.10}
TIER_WEIGHT = {"gold": 1.0, "silver": 0.7, "bronze": 0.4}
PENALTY_CAP = 50000.0
HIGH, MEDIUM = 60.0, 30.0


@dataclass(frozen=True)
class RiskResult:
    score: float
    band: str
    factors: list[dict]


def time_risk(slack_days: int | None) -> float:
    if slack_days is None or slack_days <= 0:
        return 1.0
    return 0.6 if slack_days <= 2 else 0.2


def band_for(score: float) -> str:
    return "high" if score >= HIGH else "medium" if score >= MEDIUM else "low"


def risk_score(*, uncovered_qty: int, order_qty: int, slack_days: int | None, tier: str, sla_penalty: float,
               supplier_reliability: float | None) -> RiskResult:
    shortfall = min(1.0, max(0.0, uncovered_qty / order_qty)) if order_qty > 0 else 0.0
    penalty = min(1.0, max(0.0, float(sla_penalty)) / PENALTY_CAP)
    supplier = 0.0 if supplier_reliability is None else min(1.0, max(0.0, 1 - supplier_reliability / 100))
    values = {"shortfall": shortfall, "time": time_risk(slack_days), "tier": TIER_WEIGHT.get(tier, 0.4),
              "penalty": penalty, "supplier": supplier}
    texts = {
        "shortfall": f"{uncovered_qty} of {order_qty} units cannot be covered in time",
        "time": "no slack before the due date" if time_risk(slack_days) == 1.0
        else f"{slack_days} day(s) of slack before the due date",
        "tier": f"{tier.capitalize()} customer",
        "penalty": f"SLA penalty of {float(sla_penalty):,.0f}",
        "supplier": "supplier reliability unknown" if supplier_reliability is None
        else f"supplier reliability {supplier_reliability:.0f}/100",
    }
    factors = [{"name": n, "value": round(values[n], 3), "weight": WEIGHTS[n],
                "points": round(100 * WEIGHTS[n] * values[n], 1), "text": texts[n]} for n in WEIGHTS]
    score = round(sum(f["points"] for f in factors), 1)
    return RiskResult(score, band_for(score), factors)
