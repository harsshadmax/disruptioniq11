"""Output checks for AI text. The AI may restate computed facts, never invent them (blueprint section 8, guardrail 3)."""
import re

_NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")
MAX_TEXT = 700


def _norm(token: str) -> float:
    return round(float(token.replace(",", "").rstrip(".")), 2)


def numbers_in_text(text: str) -> set[float]:
    return {_norm(t.rstrip(",")) for t in _NUMBER.findall(text)}


def allowed_numbers(data) -> set[float]:
    """Every number that appears in the input, as a number or inside a string (ids, dates, refs)."""
    out: set[float] = set()
    if isinstance(data, bool) or data is None:
        return out
    if isinstance(data, (int, float)):
        out.add(round(float(data), 2))
    elif isinstance(data, str):
        out |= numbers_in_text(data)
    elif isinstance(data, dict):
        for k, v in data.items():
            out |= numbers_in_text(str(k)) | allowed_numbers(v)
    elif isinstance(data, (list, tuple)):
        for v in data:
            out |= allowed_numbers(v)
    return out


def unsupported_numbers(text: str, data) -> list[float]:
    """Numbers in `text` that the input does not contain. Empty means the text only restates the input."""
    return sorted(numbers_in_text(text) - allowed_numbers(data))


def problem_with(text: str, data) -> str | None:
    """Why this AI text must not be used, or None when it passes."""
    t = (text or "").strip()
    if not t:
        return "empty answer"
    if len(t) > MAX_TEXT:
        return "answer too long"
    if "<" in t or ">" in t or "http" in t.lower():
        return "answer contains markup or a link"
    bad = unsupported_numbers(t, data)
    if bad:
        return "numbers not in the input: " + ", ".join(f"{b:g}" for b in bad)
    return None
