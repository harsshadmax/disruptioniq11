"""Reads of confirmed contract terms. Kept apart from service.py so the impact loader can import it without a cycle."""
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.contracts.rules import Terms
from app.models import CustomerContract


def confirmed_terms(db: Session) -> dict[int, Terms]:
    """customer_id -> the terms of that customer's confirmed contract (at most one each)."""
    rows = db.execute(select(CustomerContract.customer_id, CustomerContract.terms_json)
                      .where(CustomerContract.status == "confirmed")).all()
    return {cid: Terms(**terms) for cid, terms in rows}
