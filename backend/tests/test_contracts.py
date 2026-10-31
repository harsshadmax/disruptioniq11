"""Contract terms: the reader, the PDF reader, the AI check, and the API that makes confirmed terms change penalties."""
import json

import pytest
from sqlalchemy import func, select

from app.ai import contract_check
from app.ai.client import AiUnavailable
from app.contracts import pdf
from app.contracts.rules import Terms, max_penalty, read_terms, relevant_passages
from app.enums import Role
from app.impact.service import load_world
from app.models import AuditLog, Customer, CustomerContract, Order

from tests.conftest import auth_headers
from tests.pdfmaker import CONTRACT_LINES, make_pdf
from tests.test_workflow import fire_s1, world  # noqa: F401  (a fixture: synthetic data loaded)

TEXT = " ".join(CONTRACT_LINES)


def found(text):
    return {f.field: f.value for f in reversed(read_terms(text).findings)}


# ---- the reader (pure) ----------------------------------------------------------------------------------------

def test_the_reader_finds_each_clause_with_its_sentence():
    r = read_terms(TEXT)
    t = r.terms()
    assert (t.rate_percent, t.rate_period, t.cap_percent, t.grace_days, t.termination_days) == (2.0, "day", 10.0, 3, 14)
    assert (t.flat_amount, t.cap_amount, t.force_majeure) == (25000.0, 60000.0, True)
    assert all(f.snippet for f in r.findings) and not r.warnings


@pytest.mark.parametrize("text,expected", [
    ("liquidated damages of 1.5% per week of delay, up to a maximum of 8%", {"rate_percent": 1.5, "rate_period": "week", "cap_percent": 8.0}),
    ("capped at INR 1,25,000 in total", {"cap_amount": 125000.0}),
    ("a penalty of ₹ 5,000 per delayed order will be charged", {"flat_amount": 5000.0}),
    ("the Customer may terminate this order where delay exceeds 30 days", {"termination_days": 30}),
    ("where delay exceeds 21 days the buyer may terminate the agreement", {"termination_days": 21}),
])
def test_other_phrasings(text, expected):
    got = found(text)
    assert {k: got[k] for k in expected} == expected


def test_warnings_say_what_is_missing():
    assert any("no cap" in w for w in read_terms("The Supplier pays 2% per day of delay.").warnings)
    assert any("No penalty clause" in w for w in read_terms("The parties agree to cooperate in good faith always.").warnings)
    assert any("currency" in w for w in read_terms("Penalty of $500 per late order applies.").warnings)
    assert any("more than one value" in w for w in read_terms("capped at 10% of value. Later, capped at 12% of value.").warnings)


def test_the_first_value_is_proposed_when_there_are_several():
    assert read_terms("capped at 10% here. capped at 12% there.").terms().cap_percent == 10.0


def test_terms_are_range_checked():
    with pytest.raises(ValueError):
        Terms(cap_percent=150)
    with pytest.raises(ValueError):
        Terms(rate_period="year")
    with pytest.raises(ValueError):
        Terms(grace_days=-1)


def test_only_delay_and_penalty_sentences_go_to_the_ai_check():
    text = "The parties met in Pune. Payment is due in 30 days. A penalty of Rs. 500 applies to late orders. Colours are blue."
    assert relevant_passages(text) == "A penalty of Rs. 500 applies to late orders."
    assert len(relevant_passages("A late penalty applies. " * 2000)) <= 5000


# ---- the penalty a contract allows (pure) ---------------------------------------------------------------------

@pytest.mark.parametrize("terms,value,fallback,expected", [
    (Terms(flat_amount=25000, cap_amount=60000, cap_percent=10), 400_000, 7000, (25000.0, "contract")),
    (Terms(flat_amount=25000, cap_percent=5), 100_000, 7000, (5000.0, "contract")),  # the cap is lower than the fixed amount
    (Terms(cap_percent=10), 123_456.78, 7000, (12345.68, "contract")),
    (Terms(cap_amount=9000, cap_percent=10), 400_000, 7000, (9000.0, "contract")),
    (Terms(rate_percent=2, rate_period="day"), 400_000, 7000, (7000, "order")),  # a rate with no ceiling changes nothing
    (Terms(), 400_000, 7000, (7000, "order")),
    (Terms(flat_amount=0), 400_000, 7000, (0.0, "contract")),
])
def test_max_penalty(terms, value, fallback, expected):
    assert max_penalty(terms, value, fallback) == expected


# ---- the PDF reader -------------------------------------------------------------------------------------------

def test_text_comes_out_of_a_pdf():
    text = pdf.extract_text(make_pdf(CONTRACT_LINES))
    assert "liquidated damages" in text and "force majeure" in text


@pytest.mark.parametrize("data,message", [
    (b"not a pdf at all", "does not look like a PDF"),
    (make_pdf([], empty=True), "No text was found"),
    (b"%PDF-1.4\n" + b"\x00" * 50, "could not be read"),
    (b"%PDF-" + b"0" * (pdf.MAX_BYTES + 1), "larger than"),
])
def test_unreadable_pdfs_say_why(data, message):
    with pytest.raises(pdf.UnreadablePdf, match=message):
        pdf.extract_text(data)


# ---- the AI check ---------------------------------------------------------------------------------------------

PASSAGES = relevant_passages(TEXT)


def ai_says(monkeypatch, payload):
    monkeypatch.setattr(contract_check, "provider", lambda: "free-llm")
    monkeypatch.setattr(contract_check.settings, "check_llm_model", "test-model")
    raw = payload if isinstance(payload, str) else json.dumps(payload)
    monkeypatch.setattr(contract_check, "_call_free_llm", lambda user: raw)


def verdicts(result):
    return {c["field"]: c["verdict"] for c in result["checks"]}


def test_the_check_is_unavailable_without_a_service(monkeypatch):
    monkeypatch.setattr(contract_check, "provider", lambda: None)
    r = contract_check.verify(Terms(cap_percent=10), PASSAGES)
    assert r["available"] is False and "No AI service" in r["reason"]


def test_a_verdict_counts_only_with_a_real_quote_containing_the_number(monkeypatch):
    ai_says(monkeypatch, {"checks": [
        {"field": "cap_percent", "verdict": "supported", "quote": "capped at 10% of the order value"},
        {"field": "grace_days", "verdict": "supported", "quote": "a grace period of 4 days"},  # not in the contract
        {"field": "termination_days", "verdict": "supported", "quote": "the Customer may terminate an order"},  # no number
        {"field": "flat_amount", "verdict": "contradicted", "quote": "A fixed penalty of Rs. 25,000 per late order"},
    ], "missed": []})
    r = contract_check.verify(Terms(cap_percent=10, grace_days=3, termination_days=14, flat_amount=99999), PASSAGES)
    assert r["available"] and verdicts(r) == {"cap_percent": "supported", "grace_days": "unverified",
                                              "termination_days": "unverified", "flat_amount": "contradicted"}
    assert r["summary"] == "1 of 4 terms supported by the contract text"


def test_a_term_the_model_skips_is_unverified_not_agreed(monkeypatch):
    ai_says(monkeypatch, {"checks": [], "missed": []})
    assert verdicts(contract_check.verify(Terms(cap_percent=10), PASSAGES)) == {"cap_percent": "unverified"}


def test_missed_figures_need_a_real_quote(monkeypatch):
    ai_says(monkeypatch, {"checks": [], "missed": [
        {"what": "a cap", "quote": "capped at 10% of the order value"}, {"what": "invented", "quote": "ten million rupees on Tuesdays"}]})
    assert [m["what"] for m in contract_check.verify(Terms(cap_percent=10), PASSAGES)["missed"]] == ["a cap"]


def test_fenced_json_is_accepted_and_garbage_is_not(monkeypatch):
    ai_says(monkeypatch, '```json\n{"checks": [], "missed": []}\n```')
    assert contract_check.verify(Terms(cap_percent=10), PASSAGES)["available"]
    ai_says(monkeypatch, "I think it looks fine!")
    assert contract_check.verify(Terms(cap_percent=10), PASSAGES)["available"] is False


def test_a_failed_call_is_reported_not_raised(monkeypatch):
    monkeypatch.setattr(contract_check, "provider", lambda: "free-llm")

    def boom(user):
        raise AiUnavailable("API error (HTTPError)")

    monkeypatch.setattr(contract_check, "_call_free_llm", boom)
    assert contract_check.verify(Terms(cap_percent=10), PASSAGES) == {"available": False, "reason": "API error (HTTPError)"}


# ---- the API --------------------------------------------------------------------------------------------------

def person(world, role):  # noqa: F811
    return world[role.value]


def upload(client, user, customer_id, data=None, name="contract.pdf"):
    return client.post("/contracts/upload", headers=auth_headers(user), data={"customer_id": str(customer_id)},
                       files={"file": (name, data if data is not None else make_pdf(CONTRACT_LINES), "application/pdf")})


def customer_with_orders(db):
    return db.execute(select(Customer).join(Order, Order.customer_id == Customer.id).where(Order.status == "open")
                      .group_by(Customer.id).order_by(func.count().desc(), Customer.id)).scalars().first()


def confirm(client, user, contract_id, terms, **extra):
    return client.post(f"/contracts/{contract_id}/confirm", headers=auth_headers(user), json={"terms": terms} | extra)


def count(db, model):
    return db.execute(select(func.count()).select_from(model)).scalar_one()


def test_upload_reads_the_terms_and_changes_no_number(world, db, client):  # noqa: F811
    cust = customer_with_orders(db)
    before = [(ln.order_ref, ln.sla_penalty) for c in load_world(db).values() for ln in c.lines]
    r = upload(client, person(world, Role.ANALYST), cust.id)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "pending" and body["customer"] == cust.name and body["uploaded_by"]
    assert body["terms"]["cap_percent"] == 10.0 and {f["field"] for f in body["findings"]} >= {"cap_percent", "grace_days"}
    assert [(ln.order_ref, ln.sla_penalty) for c in load_world(db).values() for ln in c.lines] == before
    assert db.execute(select(AuditLog.action).order_by(AuditLog.id.desc())).scalars().first() == "contract.uploaded"


@pytest.mark.parametrize("data,status", [
    (b"just text", 422), (make_pdf([], empty=True), 422), (b"%PDF-" + b"0" * (pdf.MAX_BYTES + 1), 422)])
def test_bad_uploads_are_refused(world, db, client, data, status):  # noqa: F811
    r = upload(client, person(world, Role.ANALYST), customer_with_orders(db).id, data)
    assert r.status_code == status and count(db, CustomerContract) == 0


def test_an_unknown_customer_is_a_404(world, client):  # noqa: F811
    assert upload(client, person(world, Role.ANALYST), 999999).status_code == 404


@pytest.mark.parametrize("role,expected", [(Role.ANALYST, 200), (Role.MANAGER, 200), (Role.ADMIN, 200),
                                           (Role.PROCUREMENT, 403), (Role.OPERATOR, 403)])
def test_who_may_upload(world, db, client, role, expected):  # noqa: F811
    assert upload(client, person(world, role), customer_with_orders(db).id).status_code == expected


@pytest.mark.parametrize("role,expected", [(Role.ANALYST, 200), (Role.MANAGER, 200), (Role.PROCUREMENT, 200),
                                           (Role.ADMIN, 200), (Role.OPERATOR, 403)])
def test_who_may_look(world, client, role, expected):  # noqa: F811
    assert client.get("/contracts", headers=auth_headers(person(world, role))).status_code == expected


@pytest.mark.parametrize("role", [Role.ANALYST, Role.ADMIN, Role.PROCUREMENT, Role.OPERATOR])
def test_only_a_manager_can_confirm(world, db, client, role):  # noqa: F811
    cid = upload(client, person(world, Role.ANALYST), customer_with_orders(db).id).json()["id"]
    assert confirm(client, person(world, role), cid, {"cap_amount": 1000}).status_code == 403
    assert db.get(CustomerContract, cid).status == "pending"


def test_the_preview_shows_before_and_after_without_saving(world, db, client):  # noqa: F811
    cust = customer_with_orders(db)
    cid = upload(client, person(world, Role.ANALYST), cust.id).json()["id"]
    r = client.post(f"/contracts/{cid}/preview", headers=auth_headers(person(world, Role.ANALYST)), json={"flat_amount": 123})
    body = r.json()
    assert r.status_code == 200 and body["order_count"] > 0 and body["has_ceiling"]
    assert body["contract_total"] == round(123 * body["order_count"], 2) and all(o["source"] == "contract" for o in body["orders"])
    assert db.get(CustomerContract, cid).status == "pending"
    no_limit = client.post(f"/contracts/{cid}/preview", headers=auth_headers(person(world, Role.ANALYST)), json={"rate_percent": 2, "rate_period": "day"}).json()
    assert not no_limit["has_ceiling"] and no_limit["contract_total"] == no_limit["current_total"]


def test_confirming_replaces_the_penalty_and_refreshes_risk(world, db, client):  # noqa: F811
    fire_s1(client, db)
    analyst, manager = person(world, Role.ANALYST), person(world, Role.MANAGER)
    d = client.get("/disruptions", headers=auth_headers(analyst)).json()[0]
    ranked = client.get(f"/disruptions/{d['id']}/orders", headers=auth_headers(analyst)).json()
    top = ranked[0]
    cust_id = db.execute(select(Order.customer_id).where(Order.ref == top["order_ref"])).scalar_one()
    mine = [o for o in ranked if db.execute(select(Order.customer_id).where(Order.ref == o["order_ref"])).scalar_one() == cust_id]
    cid = upload(client, analyst, cust_id).json()["id"]

    r = confirm(client, manager, cid, {"flat_amount": 111})
    assert r.status_code == 200, r.text
    assert r.json()["contract"]["status"] == "confirmed" and r.json()["contract"]["decided_by"]
    after = client.get(f"/disruptions/{d['id']}/orders", headers=auth_headers(analyst)).json()
    assert {o["sla_penalty"] for o in after if o["order_ref"] in {m["order_ref"] for m in mine}} == {111.0}
    others = {o["order_ref"]: o["sla_penalty"] for o in ranked if o not in mine}
    assert {o["order_ref"]: o["sla_penalty"] for o in after if o["order_ref"] in others} == others  # nobody else changed
    assert client.get("/disruptions", headers=auth_headers(analyst)).json()[0]["penalty_exposure"] != d["penalty_exposure"]
    assert "contract.confirmed" in db.execute(select(AuditLog.action)).scalars().all()


def test_the_what_if_lab_uses_the_contract_too(world, db, client):  # noqa: F811
    analyst, manager = person(world, Role.ANALYST), person(world, Role.MANAGER)
    opts = client.get("/simulate/options", headers=auth_headers(analyst)).json()
    sup = next(s for s in opts["suppliers"] if s["name"] == "Coastal Polymers")
    run = lambda: client.post("/simulate/run", headers=auth_headers(analyst), json={"events": [{"kind": "supplier_shutdown", "supplier_id": sup["id"]}]}).json()  # noqa: E731
    before = run()
    cust_id = db.execute(select(Order.customer_id).where(Order.ref == before["orders"][0]["order_ref"])).scalar_one()
    cid = upload(client, analyst, cust_id).json()["id"]
    assert confirm(client, manager, cid, {"flat_amount": 1}).status_code == 200
    assert run()["simulated"]["penalty_exposure"] < before["simulated"]["penalty_exposure"]


def test_a_new_confirmed_contract_retires_the_old_one(world, db, client):  # noqa: F811
    analyst, manager = person(world, Role.ANALYST), person(world, Role.MANAGER)
    cust = customer_with_orders(db)
    first = upload(client, analyst, cust.id).json()["id"]
    second = upload(client, analyst, cust.id).json()["id"]
    assert confirm(client, manager, first, {"flat_amount": 100}).status_code == 200
    assert confirm(client, manager, second, {"flat_amount": 200}).status_code == 200
    db.expire_all()
    assert [db.get(CustomerContract, i).status for i in (first, second)] == ["superseded", "confirmed"]
    pen = {ln.sla_penalty for c in load_world(db).values() for ln in c.lines if ln.customer == cust.name}
    assert pen == {200.0}
    customers = {c["id"]: c for c in client.get("/contracts/customers", headers=auth_headers(analyst)).json()}
    assert customers[cust.id]["contract_id"] == second


def test_a_decided_contract_cannot_be_decided_again(world, db, client):  # noqa: F811
    analyst, manager = person(world, Role.ANALYST), person(world, Role.MANAGER)
    cid = upload(client, analyst, customer_with_orders(db).id).json()["id"]
    assert confirm(client, manager, cid, {"flat_amount": 5}).status_code == 200
    assert confirm(client, manager, cid, {"flat_amount": 6}).status_code == 409
    assert client.post(f"/contracts/{cid}/reject", headers=auth_headers(manager)).status_code == 409


def test_reject_changes_nothing(world, db, client):  # noqa: F811
    analyst, manager = person(world, Role.ANALYST), person(world, Role.MANAGER)
    cust = customer_with_orders(db)
    before = {ln.line_id: ln.sla_penalty for c in load_world(db).values() for ln in c.lines}
    cid = upload(client, analyst, cust.id).json()["id"]
    r = client.post(f"/contracts/{cid}/reject", headers=auth_headers(manager))
    assert r.status_code == 200 and r.json()["status"] == "rejected"
    assert {ln.line_id: ln.sla_penalty for c in load_world(db).values() for ln in c.lines} == before


def test_invalid_terms_are_refused(world, db, client):  # noqa: F811
    cid = upload(client, person(world, Role.ANALYST), customer_with_orders(db).id).json()["id"]
    for bad in ({"cap_percent": 500}, {"rate_period": "year"}, {"grace_days": -2}, {"flat_amount": "lots"}):
        assert confirm(client, person(world, Role.MANAGER), cid, bad).status_code == 422


def test_the_ai_check_runs_on_the_final_terms_and_can_block(world, db, client, monkeypatch):  # noqa: F811
    analyst, manager = person(world, Role.ANALYST), person(world, Role.MANAGER)
    cid = upload(client, analyst, customer_with_orders(db).id).json()["id"]
    ai_says(monkeypatch, {"checks": [{"field": "cap_percent", "verdict": "contradicted", "quote": "capped at 10% of the order value"}], "missed": []})
    blocked = confirm(client, manager, cid, {"cap_percent": 50})
    assert blocked.status_code == 409 and blocked.json()["detail"]["ai_check"]["checks"][0]["verdict"] == "contradicted"
    assert db.get(CustomerContract, cid).status == "pending" and db.get(CustomerContract, cid).ai_check_json
    ok = confirm(client, manager, cid, {"cap_percent": 50}, override_ai=True)
    assert ok.status_code == 200
    row = db.execute(select(AuditLog).where(AuditLog.action == "contract.confirmed")).scalars().one()
    assert row.reason == "confirmed despite an AI disagreement"


def test_a_supported_check_lets_the_confirmation_through(world, db, client, monkeypatch):  # noqa: F811
    cid = upload(client, person(world, Role.ANALYST), customer_with_orders(db).id).json()["id"]
    ai_says(monkeypatch, {"checks": [{"field": "cap_percent", "verdict": "supported", "quote": "capped at 10% of the order value"}], "missed": []})
    r = confirm(client, person(world, Role.MANAGER), cid, {"cap_percent": 10})
    assert r.status_code == 200 and r.json()["contract"]["ai_check"]["summary"].startswith("1 of 1")


def test_the_check_endpoint_stores_its_result(world, db, client, monkeypatch):  # noqa: F811
    cid = upload(client, person(world, Role.ANALYST), customer_with_orders(db).id).json()["id"]
    ai_says(monkeypatch, {"checks": [], "missed": []})
    r = client.post(f"/contracts/{cid}/check", headers=auth_headers(person(world, Role.ANALYST)), json={"cap_percent": 10})
    assert r.status_code == 200 and r.json()["available"] and db.get(CustomerContract, cid).ai_check_json["available"]
