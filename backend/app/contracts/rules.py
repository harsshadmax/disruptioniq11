"""Reading penalty terms out of contract text, and turning confirmed terms into a penalty. Pure: no database, no I/O.

The reader looks for a handful of well-known clause shapes ("2% per day", "capped at 10%", "grace period of 3 days").
It only ever *proposes* values, each with the sentence it came from; a person confirms or edits them before anything
uses them. Amounts are taken as Indian rupees, the currency the rest of the app uses.
"""
import re
from dataclasses import dataclass, field

from pydantic import BaseModel, Field

SNIPPET_RADIUS = 70  # characters of context kept on each side of a match
MAX_PASSAGES_CHARS = 5000  # what may be sent to an outside AI service for checking

_MONEY = r"(?:₹|rs\.?|inr)\s*([\d,]+(?:\.\d+)?)"
_NUM = r"(\d+(?:\.\d+)?)"
_DAYS = r"(\d{1,3})\s*(?:\(\w+\)\s*)?(?:calendar\s+|business\s+|working\s+)?days?"
_CAP_WORDS = r"(?:capped\s+at|cap\s+of|maximum\s+of|max\.?\s+of|not\s+(?:to\s+)?exceed(?:ing)?|up\s+to\s+(?:a\s+maximum\s+of\s+)?|shall\s+not\s+exceed)"


class Terms(BaseModel):
    """What a person confirms. Every field is optional; `None` means the contract does not say."""

    flat_amount: float | None = Field(None, ge=0, le=100_000_000)  # fixed penalty per late order, in rupees
    rate_percent: float | None = Field(None, ge=0, le=100)  # percent of order value per period of delay
    rate_period: str | None = Field(None, pattern="^(day|week)$")
    cap_percent: float | None = Field(None, ge=0, le=100)  # maximum penalty as a percent of order value
    cap_amount: float | None = Field(None, ge=0, le=100_000_000)  # maximum penalty in rupees
    grace_days: int | None = Field(None, ge=0, le=365)  # delay allowed before any penalty
    termination_days: int | None = Field(None, ge=0, le=365)  # customer may cancel after this much delay
    force_majeure: bool | None = None  # the contract has a force majeure clause

    def has_penalty_limit(self) -> bool:
        return any(v is not None for v in (self.flat_amount, self.cap_percent, self.cap_amount))


FIELD_LABELS = {
    "flat_amount": "Fixed penalty per late order (INR)",
    "rate_percent": "Penalty rate (% of order value)",
    "rate_period": "Rate applies per",
    "cap_percent": "Penalty cap (% of order value)",
    "cap_amount": "Penalty cap (INR)",
    "grace_days": "Grace period (days)",
    "termination_days": "Customer may cancel after delay of (days)",
    "force_majeure": "Force majeure clause present",
}


@dataclass
class Finding:
    field: str
    value: float | int | str | bool
    snippet: str


@dataclass
class Reading:
    findings: list[Finding] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def terms(self) -> Terms:
        """The first finding per field becomes the proposed value."""
        proposed: dict = {}
        for f in self.findings:
            proposed.setdefault(f.field, f.value)
        return Terms(**proposed)


def normalise(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").replace(" ", " ")).strip()


def _snippet(text: str, m: re.Match) -> str:
    """The match with a little context, cut at word boundaries so no word is left half."""
    lo, hi = max(0, m.start() - SNIPPET_RADIUS), min(len(text), m.end() + SNIPPET_RADIUS)
    if lo and text[lo - 1] != " ":
        lo = text.find(" ", lo, m.start()) + 1 or m.start()
    if hi < len(text) and text[hi] != " ":
        cut = text.rfind(" ", m.end(), hi)
        hi = cut if cut > 0 else m.end()
    return ("..." if lo else "") + text[lo:hi].strip() + ("..." if hi < len(text) else "")


def _amount(raw: str) -> float:
    return float(raw.replace(",", ""))


def read_terms(text: str) -> Reading:
    """Proposed terms with the sentence each one came from, in the order they appear in the contract."""
    t = normalise(text)
    out = Reading()
    add = lambda name, value, m: out.findings.append(Finding(name, value, _snippet(t, m)))  # noqa: E731

    for m in re.finditer(_NUM + r"\s*%[^.;]{0,70}?\b(?:per|for\s+each|for\s+every|each)\s+(?:calendar\s+)?(day|week)\b", t, re.I):
        add("rate_percent", float(m.group(1)), m)
        add("rate_period", m.group(2).lower(), m)
    for m in re.finditer(_CAP_WORDS + r"\s*" + _NUM + r"\s*%", t, re.I):
        add("cap_percent", float(m.group(1)), m)
    for m in re.finditer(_CAP_WORDS + r"[^.;%\d]{0,25}?" + _MONEY, t, re.I):
        add("cap_amount", _amount(m.group(1)), m)
    for m in re.finditer(r"(?:liquidated\s+damages|penalty|penalties|fine)\s+(?:of|equal\s+to|amounting\s+to)\s*" + _MONEY
                         + r"[^.;]{0,50}?\b(?:per|for\s+each|for\s+every)\s+(?:late|delayed)?\s*(?:order|delivery|shipment|breach|occurrence)", t, re.I):
        add("flat_amount", _amount(m.group(1)), m)
    for m in re.finditer(r"grace\s+period\s+of\s+" + _DAYS, t, re.I):
        add("grace_days", int(m.group(1)), m)
    for m in re.finditer(r"no\s+(?:penalty|liquidated\s+damages)[^.;]{0,40}?(?:delay|late)[^.;]{0,30}?(?:up\s+to|not\s+exceeding|of)\s+" + _DAYS, t, re.I):
        add("grace_days", int(m.group(1)), m)
    for m in re.finditer(r"terminat\w+[^.;]{0,100}?(?:delay|late)[^.;]{0,60}?(?:exceed\w*|more\s+than|beyond|over)\s+" + _DAYS, t, re.I):
        add("termination_days", int(m.group(1)), m)
    for m in re.finditer(r"(?:delay|late)\w*[^.;]{0,60}?(?:exceed\w*|more\s+than|beyond)\s+" + _DAYS + r"[^.;]{0,80}?terminat", t, re.I):
        add("termination_days", int(m.group(1)), m)
    m = re.search(r"force\s+majeure", t, re.I)
    if m:
        add("force_majeure", True, m)

    if re.search(r"(?:\$|usd|eur|€|£)\s*\d", t, re.I) and not re.search(_MONEY, t, re.I):
        out.warnings.append("Amounts in this contract look like a currency other than rupees; check every figure.")
    names = {f.field for f in out.findings}
    if not names & {"flat_amount", "cap_percent", "cap_amount"} and "rate_percent" in names:
        out.warnings.append("A penalty rate was found but no cap or fixed amount, so the largest possible penalty is unknown. "
                            "Add a cap or amount, or the order's own penalty stays in use.")
    if not names & {"flat_amount", "rate_percent", "cap_percent", "cap_amount"}:
        out.warnings.append("No penalty clause was recognised. Enter the terms by hand if the contract has one.")
    distinct = {}
    for f in out.findings:
        distinct.setdefault(f.field, set()).add(f.value)
    for name, values in distinct.items():
        if len(values) > 1 and name != "force_majeure":
            out.warnings.append(f"{FIELD_LABELS[name]}: the contract mentions more than one value; the first is proposed.")
    return out


def relevant_passages(text: str) -> str:
    """The few sentences about delay and penalty, for an outside AI check. Never the whole contract."""
    t = normalise(text)
    keys = re.compile(r"penalt|liquidated|damages|late|delay|cap|exceed|terminat|force\s+majeure|grace", re.I)
    picked, size = [], 0
    for sentence in re.split(r"(?<=[.;])\s+", t):
        if keys.search(sentence):
            if size + len(sentence) > MAX_PASSAGES_CHARS:
                break
            picked.append(sentence)
            size += len(sentence) + 1
    return " ".join(picked)


def max_penalty(terms: Terms, order_value: float, fallback: float) -> tuple[float, str]:
    """The most this customer's contract can charge for one late order, and where the number came from.

    The final delay is not known when risk is scored, so exposure uses the contract's ceiling: the fixed amount, or the
    cap (whichever is lower when both exist). Terms that name no ceiling leave the order's own penalty in place.
    """
    limits = [v for v in (terms.cap_amount, None if terms.cap_percent is None else order_value * terms.cap_percent / 100)
              if v is not None]
    if terms.flat_amount is not None:
        return round(min([terms.flat_amount, *limits]), 2), "contract"
    if limits:
        return round(min(limits), 2), "contract"
    return fallback, "order"
