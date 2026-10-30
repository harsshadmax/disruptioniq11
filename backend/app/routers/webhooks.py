import json

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response, status
from pydantic import BaseModel, ValidationError
from sqlalchemy.orm import Session

from app.audit.service import write_audit
from app.config import settings
from app.db import get_db
from app.detect.service import refresh_disruptions
from app.ingest.webhook import WEBHOOK_ROLE, CarrierEvent, process_event, signature_ok

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


class WebhookAck(BaseModel):
    outcome: str
    event_id: int | None = None
    shipment_ref: str | None = None
    detail: str | None = None


def _reject(db: Session, action: str, http_status: int, detail, reason: str, payload: dict | None = None):
    write_audit(db, actor_id=None, role=WEBHOOK_ROLE, action=action, entity_type="webhook", reason=reason,
                payload=payload or {})
    db.commit()
    raise HTTPException(http_status, detail)


MAX_BODY_BYTES = 256 * 1024  # a carrier event is a few hundred bytes; the cap applies before the signature is checked


async def _raw_body(request: Request) -> bytes:  # read async, so the handler itself can stay a plain (threadpool) def
    declared = request.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > MAX_BODY_BYTES:
        raise HTTPException(413, "Body too large")
    body = bytearray()
    async for chunk in request.stream():  # a client can lie about Content-Length, so count what actually arrives
        body += chunk
        if len(body) > MAX_BODY_BYTES:
            raise HTTPException(413, "Body too large")
    return bytes(body)


@router.post("/carrier", response_model=WebhookAck)
def carrier_webhook(
    response: Response,
    body: bytes = Depends(_raw_body),
    x_signature: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> WebhookAck:
    """Carrier status events. Authenticated by an HMAC of the body, not by a user login."""
    if not signature_ok(body, x_signature, settings.webhook_secret):
        _reject(db, "webhook.unauthorized", status.HTTP_401_UNAUTHORIZED, "Invalid or missing signature",
                "bad signature", {"bytes": len(body)})
    try:
        event = CarrierEvent.model_validate_json(body)
    except ValidationError as exc:
        problems = [{"field": ".".join(str(p) for p in e["loc"]) or None, "reason": e["msg"].removeprefix("Value error, ")}
                    for e in exc.errors()]
        _reject(db, "webhook.invalid", status.HTTP_422_UNPROCESSABLE_CONTENT, problems, "payload failed validation",
                {"problems": problems[:10]})
    except json.JSONDecodeError:  # model_validate_json normally wraps this; kept for safety
        _reject(db, "webhook.invalid", status.HTTP_422_UNPROCESSABLE_CONTENT, "Body is not valid JSON", "not json")
    result = process_event(db, event)
    if result.outcome == "applied":
        refresh_disruptions(db)
    db.commit()
    response.status_code = result.status_code
    return WebhookAck(outcome=result.outcome, event_id=result.event_id, shipment_ref=result.shipment_ref,
                      detail=result.detail)
