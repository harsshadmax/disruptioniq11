"""Contract workflow: upload and read, preview, AI check, confirm (the only step that changes a number), reject."""
import hashlib
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai import contract_check
from app.audit.service import write_audit
from app.contracts import pdf
from app.contracts.rules import FIELD_LABELS, Terms, max_penalty, read_terms, relevant_passages
from app.detect.service import DetectionReport, refresh_disruptions
from app.models import Customer, CustomerContract, Order, User


class ContractError(Exception):
    """A rule of the workflow was broken; `status` is the HTTP status to answer with."""

    def __init__(self, message: str, status: int = 409, detail: dict | None = None):
        super().__init__(message)
        self.status, self.detail = status, detail


def upload(db: Session, user: User, customer_id: int, filename: str | None, data: bytes) -> CustomerContract:
    if db.get(Customer, customer_id) is None:
        raise ContractError("Customer not found", 404)
    try:
        text = pdf.extract_text(data)
    except pdf.UnreadablePdf as exc:
        raise ContractError(str(exc), 422) from exc
    reading = read_terms(text)
    row = CustomerContract(
        customer_id=customer_id, filename=(filename or "contract.pdf")[:200], file_sha256=hashlib.sha256(data).hexdigest(),
        status="pending", text_content=text, uploaded_by=user.id,
        extracted_json={"findings": [{"field": f.field, "label": FIELD_LABELS[f.field], "value": f.value, "snippet": f.snippet}
                                     for f in reading.findings], "warnings": reading.warnings},
        terms_json=reading.terms().model_dump())
    db.add(row)
    db.flush()
    write_audit(db, actor_id=user.id, role=user.role, action="contract.uploaded", entity_type="contract", entity_id=row.id,
                payload={"customer_id": customer_id, "filename": row.filename, "sha256": row.file_sha256,
                         "terms_found": sorted({f.field for f in reading.findings})})
    return row


def get(db: Session, contract_id: int) -> CustomerContract:
    row = db.get(CustomerContract, contract_id)
    if row is None:
        raise ContractError("Contract not found", 404)
    return row


def _pending(db: Session, contract_id: int) -> CustomerContract:
    row = get(db, contract_id)
    if row.status != "pending":
        raise ContractError(f"This contract is already {row.status}.", 409)
    return row


def preview(db: Session, contract_id: int, terms: Terms) -> dict:
    """What the customer's open orders would carry under these terms, next to what they carry now."""
    row = get(db, contract_id)
    orders = db.execute(select(Order).where(Order.customer_id == row.customer_id, Order.status == "open")
                        .order_by(Order.due_date, Order.id)).scalars().all()
    lines = []
    for o in orders:
        current = float(o.sla_penalty)
        after, source = max_penalty(terms, float(o.value), current)
        lines.append({"order_ref": o.ref, "value": float(o.value), "current_penalty": current, "contract_penalty": after,
                      "source": source})
    return {"orders": lines[:50], "order_count": len(lines),
            "current_total": round(sum(x["current_penalty"] for x in lines), 2),
            "contract_total": round(sum(x["contract_penalty"] for x in lines), 2),
            "has_ceiling": terms.has_penalty_limit()}


def check(db: Session, user: User, contract_id: int, terms: Terms) -> dict:
    row = _pending(db, contract_id)
    result = contract_check.verify(terms, relevant_passages(row.text_content))
    row.ai_check_json = {**result, "checked_terms": terms.model_dump()}
    write_audit(db, actor_id=user.id, role=user.role, action="contract.checked", entity_type="contract", entity_id=row.id,
                payload={"available": result["available"], "provider": result.get("provider"), "summary": result.get("summary")})
    return row.ai_check_json


def confirm(db: Session, user: User, contract_id: int, terms: Terms, override_ai: bool) -> tuple[CustomerContract, DetectionReport | None]:
    row = _pending(db, contract_id)
    result = check(db, user, contract_id, terms)  # the terms are always checked in their final form
    contradicted = [c["label"] for c in result.get("checks", []) if c["verdict"] == "contradicted"]
    if contradicted and not override_ai:
        raise ContractError("The AI check found the contract says something different for: " + ", ".join(contradicted)
                            + ". Fix the values or confirm anyway.", 409, {"ai_check": result})
    now = datetime.now(timezone.utc)
    for old in db.execute(select(CustomerContract).where(CustomerContract.customer_id == row.customer_id,
                                                         CustomerContract.status == "confirmed")).scalars():
        old.status = "superseded"
    db.flush()  # the old one must leave "confirmed" before the new one enters it (partial unique index)
    row.status, row.terms_json, row.decided_by, row.decided_at = "confirmed", terms.model_dump(), user.id, now
    write_audit(db, actor_id=user.id, role=user.role, action="contract.confirmed", entity_type="contract", entity_id=row.id,
                reason="confirmed despite an AI disagreement" if contradicted else None,
                payload={"customer_id": row.customer_id, "terms": row.terms_json, "ai": result.get("summary")})
    report = refresh_disruptions(db)  # penalties changed, so risk and exposure are recomputed now
    return row, report


def reject(db: Session, user: User, contract_id: int) -> CustomerContract:
    row = _pending(db, contract_id)
    row.status, row.decided_by, row.decided_at = "rejected", user.id, datetime.now(timezone.utc)
    write_audit(db, actor_id=user.id, role=user.role, action="contract.rejected", entity_type="contract", entity_id=row.id,
                payload={"customer_id": row.customer_id})
    return row
