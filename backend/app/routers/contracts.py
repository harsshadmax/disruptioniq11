from datetime import datetime

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth.deps import require
from app.contracts import pdf, service
from app.contracts.rules import Terms
from app.db import get_db
from app.models import Customer, CustomerContract, Order, User

router = APIRouter(prefix="/contracts", tags=["contracts"])


class FindingOut(BaseModel):
    field: str
    label: str
    value: float | int | str | bool
    snippet: str


class ContractOut(BaseModel):
    id: int
    customer_id: int
    customer: str
    filename: str | None
    status: str  # pending | confirmed | superseded | rejected
    uploaded_at: datetime
    uploaded_by: str | None
    decided_at: datetime | None
    decided_by: str | None
    terms: Terms
    findings: list[FindingOut]
    warnings: list[str]
    ai_check: dict | None


class CustomerOut(BaseModel):
    id: int
    name: str
    tier: str
    open_orders: int
    contract_id: int | None  # the confirmed contract, if any


class PreviewOrder(BaseModel):
    order_ref: str
    value: float
    current_penalty: float
    contract_penalty: float
    source: str  # "contract", or "order" when the order's own penalty stays


class PreviewOut(BaseModel):
    orders: list[PreviewOrder]
    order_count: int
    current_total: float
    contract_total: float
    has_ceiling: bool


class ConfirmIn(BaseModel):
    terms: Terms
    override_ai: bool = False


class ConfirmOut(BaseModel):
    contract: ContractOut
    disruptions_updated: int


def _out(db: Session, c: CustomerContract) -> ContractOut:
    ids = [i for i in (c.uploaded_by, c.decided_by) if i]
    names = {u.id: u.name for u in db.execute(select(User).where(User.id.in_(ids))).scalars()} if ids else {}
    return ContractOut(
        id=c.id, customer_id=c.customer_id, customer=db.get(Customer, c.customer_id).name, filename=c.filename, status=c.status,
        uploaded_at=c.uploaded_at, uploaded_by=names.get(c.uploaded_by), decided_at=c.decided_at, decided_by=names.get(c.decided_by),
        terms=Terms(**c.terms_json), findings=c.extracted_json.get("findings", []), warnings=c.extracted_json.get("warnings", []),
        ai_check=c.ai_check_json)


def _failed(exc: service.ContractError) -> HTTPException:
    return HTTPException(exc.status, detail={"message": str(exc), **exc.detail} if exc.detail else str(exc))


@router.get("", response_model=list[ContractOut])
def list_contracts(user: User = Depends(require("contract.view")), db: Session = Depends(get_db)) -> list[ContractOut]:
    rows = db.execute(select(CustomerContract).order_by(CustomerContract.uploaded_at.desc(), CustomerContract.id.desc()).limit(100)).scalars()
    return [_out(db, c) for c in rows]


@router.get("/customers", response_model=list[CustomerOut])
def customers(user: User = Depends(require("contract.view")), db: Session = Depends(get_db)) -> list[CustomerOut]:
    open_orders = dict(db.execute(select(Order.customer_id, func.count()).where(Order.status == "open").group_by(Order.customer_id)).all())
    confirmed = dict(db.execute(select(CustomerContract.customer_id, CustomerContract.id).where(CustomerContract.status == "confirmed")).all())
    return [CustomerOut(id=c.id, name=c.name, tier=c.tier, open_orders=open_orders.get(c.id, 0), contract_id=confirmed.get(c.id))
            for c in db.execute(select(Customer).order_by(Customer.name)).scalars()]


@router.post("/upload", response_model=ContractOut)
def upload(customer_id: int = Form(...), file: UploadFile = File(...),
           user: User = Depends(require("contract.upload")), db: Session = Depends(get_db)) -> ContractOut:
    data = file.file.read(pdf.MAX_BYTES + 1)  # one byte over the limit is enough to refuse it
    try:
        row = service.upload(db, user, customer_id, file.filename, data)
    except service.ContractError as exc:
        raise _failed(exc)
    db.commit()
    return _out(db, row)


@router.get("/{contract_id}", response_model=ContractOut)
def detail(contract_id: int, user: User = Depends(require("contract.view")), db: Session = Depends(get_db)) -> ContractOut:
    try:
        return _out(db, service.get(db, contract_id))
    except service.ContractError as exc:
        raise _failed(exc)


@router.post("/{contract_id}/preview", response_model=PreviewOut)
def preview(contract_id: int, terms: Terms, user: User = Depends(require("contract.view")), db: Session = Depends(get_db)) -> dict:
    try:
        return service.preview(db, contract_id, terms)
    except service.ContractError as exc:
        raise _failed(exc)


@router.post("/{contract_id}/check")
def check(contract_id: int, terms: Terms, user: User = Depends(require("contract.upload")), db: Session = Depends(get_db)) -> dict:
    try:
        result = service.check(db, user, contract_id, terms)
    except service.ContractError as exc:
        raise _failed(exc)
    db.commit()
    return result


@router.post("/{contract_id}/confirm", response_model=ConfirmOut)
def confirm(contract_id: int, body: ConfirmIn, user: User = Depends(require("contract.confirm")), db: Session = Depends(get_db)) -> ConfirmOut:
    try:
        row, report = service.confirm(db, user, contract_id, body.terms, body.override_ai)
    except service.ContractError as exc:
        db.commit() if exc.detail else db.rollback()  # keep the AI check that blocked it, and its audit row
        raise _failed(exc)
    db.commit()
    return ConfirmOut(contract=_out(db, row), disruptions_updated=len(report.updated) if report else 0)


@router.post("/{contract_id}/reject", response_model=ContractOut)
def reject(contract_id: int, user: User = Depends(require("contract.confirm")), db: Session = Depends(get_db)) -> ContractOut:
    try:
        row = service.reject(db, user, contract_id)
    except service.ContractError as exc:
        raise _failed(exc)
    db.commit()
    return _out(db, row)
