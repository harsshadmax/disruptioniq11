from datetime import date

import pytest
from sqlalchemy import func, select

from app.models import Customer, Inventory, Order, OrderLine, Shipment, Sku, Supplier, SupplierItem, Warehouse
from app.synth.generator import S1_SKU, S2_SKU, generate
from app.synth.loader import SynthAlreadyLoaded, load_synth, reset_domain_data

TODAY = date(2026, 11, 2)


def test_generator_is_repeatable_for_same_seed_and_date():
    assert generate(42, TODAY) == generate(42, TODAY)


def test_different_seed_changes_the_data():
    assert generate(42, TODAY) != generate(7, TODAY)


def test_sizes_match_the_blueprint():
    d = generate(42, TODAY)
    assert len(d["suppliers"]) == 6 and len(d["warehouses"]) == 4 and len(d["skus"]) == 20
    assert len(d["customers"]) == 12 and len(d["shipments"]) == 15
    assert 55 <= len(d["orders"]) <= 65
    assert {c["tier"] for c in d["customers"]} == {"gold", "silver", "bronze"}
    assert len(d["inventory"]) == 4 * 20 and len(d["transfer_costs"]) == 12


def test_every_sku_has_a_primary_and_an_alternative_supplier():
    d = generate(42, TODAY)
    per_sku: dict[str, int] = {}
    for si in d["supplier_items"]:
        per_sku[si["sku"]] = per_sku.get(si["sku"], 0) + 1
    assert set(per_sku) == {s["code"] for s in d["skus"]} and min(per_sku.values()) >= 2


def test_natural_keys_resolve_and_values_are_sane():
    d = generate(42, TODAY)
    wh, sku, sup = ({r[k] for r in d[t]} for t, k in (("warehouses", "name"), ("skus", "code"), ("suppliers", "name")))
    cust = {c["name"] for c in d["customers"]}
    assert len({o["ref"] for o in d["orders"]}) == len(d["orders"])
    for o in d["orders"]:
        assert o["customer"] in cust and o["due_date"] > o["order_date"] and o["lines"]
        for ln in o["lines"]:
            assert ln["sku"] in sku and ln["warehouse"] in wh and ln["qty"] > 0
    for s in d["shipments"]:
        assert s["supplier"] in sup and s["dest_warehouse"] in wh and s["promised_eta"].tzinfo is not None
        assert all(ln["sku"] in sku and ln["qty_expected"] > 0 for ln in s["lines"])


def test_scenario_scaffolding_exists_and_is_covered_before_any_delay():
    d = generate(42, TODAY)
    refs = {s["ref"]: s for s in d["shipments"]}
    assert refs["SHP-1042"]["supplier"] == "Coastal Polymers" and refs["SHP-1042"]["dest_warehouse"] == "Chennai"
    assert refs["SHP-1077"]["supplier"] == "Metro Components" and refs["SHP-1077"]["dest_warehouse"] == "Mumbai"
    for wh, code, ship in (("Chennai", S1_SKU, "SHP-1042"), ("Mumbai", S2_SKU, "SHP-1077")):
        demand = sum(ln["qty"] for o in d["orders"] for ln in o["lines"] if ln["warehouse"] == wh and ln["sku"] == code)
        on_hand = next(i["on_hand"] for i in d["inventory"] if i["warehouse"] == wh and i["sku"] == code)
        inbound = refs[ship]["lines"][0]["qty_expected"]
        assert demand <= on_hand + inbound  # fine until the carrier event arrives
        assert demand > on_hand  # ...but the order book really does depend on the shipment


def test_load_writes_linked_rows_and_refuses_a_second_load(db):
    counts = load_synth(db, generate(42, TODAY), seed=42)
    assert counts["orders"] == db.execute(select(func.count(Order.id))).scalar_one()
    assert db.execute(select(func.count(Supplier.id))).scalar_one() == 6
    assert db.execute(select(func.count(Shipment.id))).scalar_one() == 15
    assert db.execute(select(func.count(Inventory.sku_id))).scalar_one() == 80
    assert db.execute(select(func.count(OrderLine.id))).scalar_one() == counts["order_lines"]
    assert db.execute(select(func.count(SupplierItem.sku_id))).scalar_one() >= 40
    with pytest.raises(SynthAlreadyLoaded):
        load_synth(db, generate(42, TODAY))


def test_load_reuses_warehouses_that_users_point_at(db, users):
    operator = users["warehouse_operator"]
    chennai_id = operator.warehouse_id
    load_synth(db, generate(42, TODAY))
    assert db.get(Warehouse, chennai_id).name == "Chennai"
    assert db.execute(select(func.count(Warehouse.id))).scalar_one() == 4


def test_reset_clears_domain_data_but_keeps_users_and_allows_reload(db, users):
    load_synth(db, generate(42, TODAY))
    reset_domain_data(db)
    assert db.execute(select(func.count(Sku.id))).scalar_one() == 0
    assert db.execute(select(func.count(Customer.id))).scalar_one() == 0
    assert users["administrator"].is_active
    load_synth(db, generate(42, TODAY))
