"""The only module that imports the Anthropic SDK. Everything else in ai/ calls complete() and handles AiUnavailable."""
import logging

from app.config import settings

log = logging.getLogger(__name__)

DEFAULT_MODEL = "claude-opus-5-5"
MAX_TOKENS = 4000  # thinking is always on for this model and counts towards the limit
TIMEOUT_SECONDS = 20.0


class AiUnavailable(Exception):
    """No key, API error, refusal or truncated answer. Callers fall back to their template."""


def enabled() -> bool:
    return bool(settings.anthropic_api_key)


def model_name() -> str:
    return settings.anthropic_model or DEFAULT_MODEL


_client = None


def _get_client():
    global _client
    if _client is None:
        import anthropic  # imported here only: the app runs without a key or a configured client

        _client = anthropic.Anthropic(api_key=settings.anthropic_api_key, timeout=TIMEOUT_SECONDS, max_retries=1)
    return _client


def complete(system: str, user: str, schema: dict | None = None) -> str:
    """One request, one text answer (JSON text when a schema is given). Raises AiUnavailable on any failure."""
    if not enabled():
        raise AiUnavailable("no API key configured")
    output_config: dict = {"effort": "low"}
    if schema is not None:
        output_config["format"] = {"type": "json_schema", "schema": schema}
    try:
        resp = _get_client().messages.create(
            model=model_name(), max_tokens=MAX_TOKENS, system=system,
            messages=[{"role": "user", "content": user}], output_config=output_config)
    except Exception as exc:  # noqa: BLE001 - any SDK or network failure means "use the template"
        log.warning("AI call failed: %s", exc.__class__.__name__)
        raise AiUnavailable(f"API error ({exc.__class__.__name__})") from exc
    if resp.stop_reason in ("refusal", "max_tokens"):
        raise AiUnavailable(f"model stopped: {resp.stop_reason}")
    text = next((b.text for b in resp.content if b.type == "text"), "")
    if not text.strip():
        raise AiUnavailable("empty response")
    return text
