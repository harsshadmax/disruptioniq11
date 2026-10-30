from datetime import date

import pytest
from sqlalchemy import func, select

from app.audit.service import verify_chain
from app.models import AuditLog, ImportRowError, Inventory, Order, OrderLine, Shipment, ShipmentLine, Sku, Warehouse
from app.synth.generator import generate
from app.synth.loader import load_synth

from tests.conftest import auth_headers

TODAY = date(2026, 11, 2)
HEADER = "order_ref,customer,order_date,due_date,sku,warehouse,qty,sla_penalty\n"


@pytest.fixture
def loaded(db, users):
    load_synth(db, generate(42, TODAY), seed=42)
    return users


def post_csv(client, user, text, entity="orders", name="data.csv"):
    return client.post(f"/import/csv?entity={entity}", headers=auth_headers(user),
                       files={"file": (name, text.encode("utf-8"), "text/csv")})


def errors_by_row(body):
    out: dict[int, list[dict]] = {}
    for e in body["errors"]:
        out.setdefault(e["row_no"], []).append(e)
    return out


def test_good_orders_csv_imports_and_is_audited(client, loaded, db):
    text = HEADER + (
        "ORD-9001,Sundaram Auto Parts,2026-11-01,2026-11-10,SKU-002,Chennai,20,5000\n"
        "ORD-9001,Sundaram Auto Parts,2026-11-01,2026-11-10,SKU-003,Chennai,10,5000\n"
        "ORD-9002,Kaveri Appliances,2026-11-01,2026-11-12,SKU-004,Bengaluru,15,0\n"
    )
    r = post_csv(client, loaded["ops_analyst"], text)
    assert r.status_code == 200, r.text
    body = r.json()
    assert (body["rows_total"], body["rows_ok"], body["rows_failed"], body["errors"]) == (3, 3, 0, [])
    order = db.execute(select(Order).where(Order.ref == "ORD-9001")).scalar_one()
    assert order.status == "open" and order.value > 0
    assert db.execute(select(func.count(OrderLine.id)).where(OrderLine.order_id == order.id)).scalar_one() == 2
    audit = db.execute(select(AuditLog).where(AuditLog.action == "import.run")).scalar_one()
    assert audit.payload_json["rows_ok"] == 3 and audit.entity_id == str(body["batch_id"])


def test_bad_rows_are_reported_and_good_rows_still_import(client, loaded, db):
    text = HEADER + (
        "ORD-9101,Sundaram Auto Parts,2026-11-01,2026-11-10,SKU-002,Chennai,20,0\n"       # row 2 ok
        "ORD-9102,Sundaram Auto Parts,2026-11-01,2026-11-10,SKU-002,Chennai,-5,0\n"       # row 3 negative qty
        "ORD-9103,Sundaram Auto Parts,2026-11-10,2026-11-01,SKU-002,Chennai,5,0\n"        # row 4 due before order
        "ORD-9104,Kaveri Appliances,2026-11-01,2026-11-10,SKU-002,Chennai,abc,0\n"        # row 5 qty not a number
        "ORD-9105,Kaveri Appliances,2026-11-01,2026-11-10,SKU-999,Chennai,5,0\n"          # row 6 unknown SKU
        "ORD-9106,Nobody Ltd,2026-11-01,2026-11-10,SKU-002,Chennai,5,0\n"                 # row 7 unknown customer
        "ORD-9107,Kaveri Appliances,2026-11-01,2026-11-10,SKU-002,Atlantis,5,0\n"         # row 8 unknown warehouse
        "ORD-9108,Kaveri Appliances,2026-13-45,2026-11-10,SKU-002,Chennai,5,0\n"          # row 9 impossible date
        "ORD-9109,Kaveri Appliances,2026-11-01,2026-11-10,SKU-003,Chennai,12,0\n"         # row 10 ok
    )
    body = post_csv(client, loaded["ops_analyst"], text).json()
    assert (body["rows_total"], body["rows_ok"], body["rows_failed"]) == (9, 2, 7)
    by_row = errors_by_row(body)
    assert sorted(by_row) == [3, 4, 5, 6, 7, 8, 9]
    assert by_row[3][0]["field"] == "qty"
    assert by_row[4][0]["field"] == "due_date" and "after order_date" in by_row[4][0]["reason"]
    assert by_row[6][0]["field"] == "sku" and "SKU-999" in by_row[6][0]["reason"]
    assert by_row[7][0]["field"] == "customer"
    assert by_row[8][0]["field"] == "warehouse"
    assert by_row[9][0]["field"] == "order_date"
    refs = set(db.execute(select(Order.ref).where(Order.ref.like("ORD-91%"))).scalars())
    assert refs == {"ORD-9101", "ORD-9109"}


def test_one_bad_line_rejects_the_whole_order(client, loaded, db):
    text = HEADER + (
        "ORD-9201,Sundaram Auto Parts,2026-11-01,2026-11-10,SKU-002,Chennai,20,0\n"
        "ORD-9201,Sundaram Auto Parts,2026-11-01,2026-11-10,SKU-003,Chennai,0,0\n"
    )
    body = post_csv(client, loaded["ops_analyst"], text).json()
    assert (body["rows_ok"], body["rows_failed"]) == (0, 2)
    by_row = errors_by_row(body)
    assert by_row[3][0]["field"] == "qty"
    assert "not imported" in by_row[2][0]["reason"] and "row 3" in by_row[2][0]["reason"]
    assert db.execute(select(Order).where(Order.ref == "ORD-9201")).first() is None


def test_conflicting_header_fields_on_one_order_are_rejected(client, loaded, db):
    text = HEADER + (
        "ORD-9301,Sundaram Auto Parts,2026-11-01,2026-11-10,SKU-002,Chennai,20,0\n"
        "ORD-9301,Kaveri Appliances,2026-11-01,2026-11-10,SKU-003,Chennai,10,0\n"
    )
    body = post_csv(client, loaded["ops_analyst"], text).json()
    assert body["rows_ok"] == 0
    assert any(e["row_no"] == 3 and e["field"] == "customer" for e in body["errors"])


def test_reuploading_the_same_file_never_duplicates_or_overwrites(client, loaded, db):
    text = HEADER + "ORD-9401,Sundaram Auto Parts,2026-11-01,2026-11-10,SKU-002,Chennai,20,0\n"
    assert post_csv(client, loaded["ops_analyst"], text).json()["rows_ok"] == 1
    again = post_csv(client, loaded["ops_analyst"], text).json()
    assert again["rows_ok"] == 0 and "already exists" in again["errors"][0]["reason"]
    assert db.execute(select(func.count(Order.id)).where(Order.ref == "ORD-9401")).scalar_one() == 1


def test_file_level_problems_are_422(client, loaded):
    missing = post_csv(client, loaded["ops_analyst"], "order_ref,customer\nA,B\n")
    assert missing.status_code == 422 and "due_date" in missing.json()["detail"]
    r = client.post("/import/csv?entity=orders", headers=auth_headers(loaded["ops_analyst"]),
                    files={"file": ("x.csv", b"\xff\xfe\x00bad", "text/csv")})
    assert r.status_code == 422
    r = client.post("/import/csv?entity=customers", headers=auth_headers(loaded["ops_analyst"]),
                    files={"file": ("x.csv", b"a\n1\n", "text/csv")})
    assert r.status_code == 422


def test_row_with_too_many_cells_is_reported(client, loaded):
    text = HEADER + "ORD-9501,Sundaram Auto Parts,2026-11-01,2026-11-10,SKU-002,Chennai,20,0,extra,cells\n"
    body = post_csv(client, loaded["ops_analyst"], text).json()
    assert body["rows_ok"] == 0 and body["errors"][0]["reason"] == "too many columns"


def test_utf8_bom_and_blank_optional_cells_are_accepted(client, loaded):
    raw = ("﻿" + HEADER + "ORD-9601,Sundaram Auto Parts,2026-11-01,2026-11-10,SKU-002,Chennai,20,\n").encode()
    r = client.post("/import/csv?entity=orders", headers=auth_headers(loaded["ops_analyst"]),
                    files={"file": ("bom.csv", raw, "text/csv")})
    assert r.json()["rows_ok"] == 1


def test_only_import_roles_may_import(client, loaded):
    text = HEADER + "ORD-9701,Sundaram Auto Parts,2026-11-01,2026-11-10,SKU-002,Chennai,20,0\n"
    for role in ("warehouse_operator", "supply_chain_manager", "procurement_approver"):
        assert post_csv(client, loaded[role], text).status_code == 403
    assert post_csv(client, loaded["administrator"], text).status_code == 200
    assert client.post("/import/csv?entity=orders", files={"file": ("a.csv", b"x", "text/csv")}).status_code == 401


def test_json_import_with_bad_and_non_object_rows(client, loaded, db):
    rows = [
        {"order_ref": "ORD-9801", "customer": "Sundaram Auto Parts", "order_date": "2026-11-01",
         "due_date": "2026-11-09", "sku": "SKU-002", "warehouse": "Chennai", "qty": 7},
        {"order_ref": "ORD-9802", "customer": "Sundaram Auto Parts", "order_date": "2026-11-01",
         "due_date": "2026-11-09", "sku": "SKU-002", "warehouse": "Chennai", "qty": "seven"},
        "not an object",
    ]
    body = client.post("/import/json", headers=auth_headers(loaded["ops_analyst"]),
                       json={"entity": "orders", "rows": rows}).json()
    assert (body["source"], body["rows_ok"], body["rows_failed"]) == ("json", 1, 2)
    assert {e["row_no"] for e in body["errors"]} == {2, 3}


def test_inventory_import_updates_stock_and_rejects_bad_rows(client, loaded, db):
    text = ("warehouse,sku,on_hand,safety_stock\n"
            "Chennai,SKU-002,321,15\n"
            "Chennai,SKU-003,-1,5\n"
            "Mumbai,SKU-002,10,\n"
            "Mumbai,SKU-002,11,\n")
    body = post_csv(client, loaded["ops_analyst"], text, entity="inventory").json()
    assert (body["rows_ok"], body["rows_failed"]) == (1, 3)  # the repeated Mumbai pair rejects the pair
    chennai = db.execute(select(Warehouse).where(Warehouse.name == "Chennai")).scalar_one()
    sku = db.execute(select(Sku).where(Sku.code == "SKU-002")).scalar_one()
    inv = db.get(Inventory, (chennai.id, sku.id))
    assert inv.on_hand == 321 and inv.safety_stock == 15


def test_shipment_import_creates_shipment_with_lines_and_defaults_to_utc(client, loaded, db):
    text = ("shipment_ref,supplier,carrier,dest_warehouse,promised_eta,sku,qty\n"
            "SHP-9001,Apex Electricals,RailConnect,Delhi,2026-11-09T10:00:00,SKU-007,120\n"
            "SHP-9001,Apex Electricals,RailConnect,Delhi,2026-11-09T10:00:00,SKU-008,80\n"
            "SHP-1042,Coastal Polymers,SeaLink Logistics,Chennai,2026-11-09T10:00:00,SKU-001,5\n")
    body = post_csv(client, loaded["ops_analyst"], text, entity="shipments").json()
    assert (body["rows_ok"], body["rows_failed"]) == (2, 1)
    assert "already exists" in body["errors"][0]["reason"]
    ship = db.execute(select(Shipment).where(Shipment.ref == "SHP-9001")).scalar_one()
    assert ship.promised_eta.utcoffset().total_seconds() == 0 and ship.current_eta == ship.promised_eta
    assert db.execute(select(func.count(ShipmentLine.sku_id)).where(ShipmentLine.shipment_id == ship.id)).scalar_one() == 2


def test_batch_endpoints_expose_the_error_report(client, loaded):
    text = HEADER + "ORD-9901,Nobody Ltd,2026-11-01,2026-11-10,SKU-002,Chennai,20,0\n"
    batch_id = post_csv(client, loaded["ops_analyst"], text).json()["batch_id"]
    detail = client.get(f"/import/batches/{batch_id}", headers=auth_headers(loaded["warehouse_operator"])).json()
    assert detail["rows_failed"] == 1 and detail["errors"][0]["field"] == "customer"
    listing = client.get("/import/batches", headers=auth_headers(loaded["warehouse_operator"])).json()
    assert listing[0]["batch_id"] == batch_id
    assert client.get("/import/batches/999999", headers=auth_headers(loaded["ops_analyst"])).status_code == 404


def test_errors_are_persisted_and_audit_chain_stays_valid(client, loaded, db):
    text = HEADER + "ORD-9902,Nobody Ltd,2026-11-01,2026-11-10,SKU-002,Chennai,20,0\n"
    batch_id = post_csv(client, loaded["ops_analyst"], text).json()["batch_id"]
    assert db.execute(select(func.count(ImportRowError.id)).where(ImportRowError.batch_id == batch_id)).scalar_one() == 1
    assert verify_chain(db)[0] is True


def test_files_between_the_old_and_new_size_cap_are_accepted(client, loaded):
    pad = "ORD-9300,Sundaram Auto Parts,2026-11-01,2026-11-10,SKU-002,Chennai,abc,0," + "x" * 400 + "\n"
    text = HEADER + pad * 6000  # about 2.5 MB and 6,000 rows: over the old limits, bad rows only, so no database work
    assert 2 * 1024 * 1024 < len(text.encode()) < 10 * 1024 * 1024
    r = post_csv(client, loaded["ops_analyst"], text)
    assert r.status_code == 200, r.text
    assert r.json()["rows_failed"] >= 1


def test_row_and_size_caps_still_hold(client, loaded):
    too_many = HEADER + "ORD-9400,Sundaram Auto Parts,2026-11-01,2026-11-10,SKU-002,Chennai,abc,0\n" * 10_001
    r = post_csv(client, loaded["ops_analyst"], too_many)
    assert r.status_code == 413 and "10000" in r.json()["detail"]
    too_big = HEADER + ("x" * 1000 + "\n") * 11_000  # over 10 MB
    r = post_csv(client, loaded["ops_analyst"], too_big)
    assert r.status_code == 413 and "10 MB" in r.json()["detail"]
