"""Deterministic synthetic data (blueprint section 8).

`generate(seed, today)` is a pure function: same seed and same `today` give identical output, so
demos and tests are repeatable. Rows reference each other by natural key (name, code, ref) and are
turned into database ids by `app.synth.loader`.

The two disruption scenarios are scaffolded in the data, not hard-coded in the rules:
  S1  shipment SHP-1042 (Coastal Polymers -> Chennai, SKU-001) with 7 Chennai orders that rely on it
  S2  shipment SHP-1077 (Metro Components -> Mumbai, SKU-006) with 5 Mumbai orders that rely on it
Everything is covered by stock and inbound supply until a scenario event arrives.
"""
import random
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal

SYNTHETIC_NOTICE = "Synthetic demo data"

S1_SHIPMENT, S1_SKU, S1_WAREHOUSE, S1_SUPPLIER = "SHP-1042", "SKU-001", "Chennai", "Coastal Polymers"
S2_SHIPMENT, S2_SKU, S2_WAREHOUSE, S2_SUPPLIER = "SHP-1077", "SKU-006", "Mumbai", "Metro Components"
SCENARIO_CELLS = {(S1_WAREHOUSE, S1_SKU), (S2_WAREHOUSE, S2_SKU), ("Bengaluru", S1_SKU), ("Delhi", S2_SKU)}

WAREHOUSES = ["Chennai", "Bengaluru", "Mumbai", "Delhi"]
CARRIERS = ["SeaLink Logistics", "RoadRunner Freight", "AirSwift Cargo", "RailConnect"]

# name, baseline lead days, reliability 0..100
SUPPLIERS = [
    ("Coastal Polymers", 9, 74.0),
    ("Metro Components", 7, 68.0),
    ("Apex Electricals", 6, 88.0),
    ("Southern Packaging", 5, 92.0),
    ("Northline Metals", 10, 81.0),
    ("Deccan Plastics", 8, 85.0),
]

# 20 SKUs in four families; unit cost in whole rupees. (name, unit_cost, primary supplier, alternative supplier)
_FAMILIES = [
    ("Coastal Polymers", "Deccan Plastics", [
        ("HDPE Resin Pellets 25kg", 1850), ("PVC Compound Granules 25kg", 1620), ("Polypropylene Sheet 2mm", 940),
        ("Nylon 6 Filament Spool", 2300), ("ABS Moulding Pellets 25kg", 2050)]),
    ("Metro Components", "Apex Electricals", [
        ("Control Relay Module", 640), ("Industrial Contactor 24V", 880), ("Thermal Overload Switch", 410),
        ("Terminal Block Strip", 120), ("PLC I/O Card 16ch", 3900)]),
    ("Northline Metals", "Apex Electricals", [
        ("Steel Bracket 40mm", 95), ("Aluminium Extrusion 2m", 720), ("Copper Busbar 1m", 1350),
        ("Fastener Kit M8 (100)", 260), ("Galvanised Sheet 1.2mm", 1480)]),
    ("Southern Packaging", "Deccan Plastics", [
        ("Corrugated Carton 5-ply", 38), ("Stretch Film Roll 500mm", 310), ("Foam Insert Set", 54),
        ("Pallet Strapping Reel", 420), ("Label Roll Thermal 100mm", 150)]),
]
SKU_COUNT = sum(len(f[2]) for f in _FAMILIES)

CUSTOMERS = [  # name, city, tier (gold never takes partial shipments; silver/bronze below)
    ("Sundaram Auto Parts", "Chennai", "gold"),
    ("Kaveri Appliances", "Bengaluru", "gold"),
    ("Western Grid Industries", "Mumbai", "gold"),
    ("Marina Engineering Works", "Chennai", "silver"),
    ("Lalbagh Electronics", "Bengaluru", "silver"),
    ("Konkan Fabricators", "Mumbai", "silver"),
    ("Yamuna Switchgear", "Delhi", "silver"),
    ("Adyar Packaging Co", "Chennai", "bronze"),
    ("Whitefield Tools", "Bengaluru", "bronze"),
    ("Thane Hardware Mart", "Mumbai", "bronze"),
    ("Okhla Precision Parts", "Delhi", "bronze"),
    ("Gurgaon Retail Supplies", "Delhi", "bronze"),
]

PARTIAL_OK = {"Konkan Fabricators", "Yamuna Switchgear", "Lalbagh Electronics", "Adyar Packaging Co",
              "Thane Hardware Mart", "Okhla Precision Parts", "Gurgaon Retail Supplies"}  # accept split shipments

_TRANSFER = {  # (a, b): (cost per unit in rupees, transit days); used in both directions
    ("Chennai", "Bengaluru"): (4, 1), ("Chennai", "Mumbai"): (9, 3), ("Chennai", "Delhi"): (14, 4),
    ("Bengaluru", "Mumbai"): (7, 2), ("Bengaluru", "Delhi"): (12, 4), ("Mumbai", "Delhi"): (8, 2),
}

_PENALTY = {"gold": [25000, 40000, 60000], "silver": [10000, 20000], "bronze": [0, 2000, 5000]}
_VALUE_MARKUP = Decimal("1.35")
_CENT = Decimal("0.01")


def _sku_code(n: int) -> str:
    return f"SKU-{n:03d}"


def _money(x) -> Decimal:
    return Decimal(x).quantize(_CENT)


def _eta(today: date, days: int) -> datetime:
    return datetime.combine(today + timedelta(days=days), time(10, 0), tzinfo=timezone.utc)


def generate(seed: int = 42, today: date | None = None) -> dict[str, list[dict]]:
    today = today or date.today()
    rng = random.Random(seed)

    suppliers = [{"name": n, "baseline_lead_days": lead, "reliability_score": rel} for n, lead, rel in SUPPLIERS]
    sup_lead = {n: lead for n, lead, _ in SUPPLIERS}

    skus: list[dict] = []
    supplier_items: list[dict] = []
    sku_cost: dict[str, Decimal] = {}
    primary_of: dict[str, str] = {}
    n = 0
    for primary, alt, items in _FAMILIES:
        for name, cost in items:
            n += 1
            code = _sku_code(n)
            sku_cost[code] = _money(cost)
            primary_of[code] = primary
            skus.append({"code": code, "name": name, "unit_cost": _money(cost),
                         "safety_stock_default": rng.randint(10, 40)})
            supplier_items.append({"supplier": primary, "sku": code, "unit_price": _money(cost * Decimal("0.92")),
                                   "lead_days": sup_lead[primary] + rng.randint(-1, 2)})
            supplier_items.append({"supplier": alt, "sku": code,
                                   "unit_price": _money(cost * Decimal(str(round(rng.uniform(1.08, 1.18), 2)))),
                                   "lead_days": max(2, sup_lead[alt] + rng.randint(-2, 1))})
    sku_codes = [s["code"] for s in skus]
    safety = {s["code"]: s["safety_stock_default"] for s in skus}

    on_hand_override = {(S1_WAREHOUSE, S1_SKU): 40, ("Bengaluru", S1_SKU): 600,
                        (S2_WAREHOUSE, S2_SKU): 60, ("Delhi", S2_SKU): 300}
    inventory = [
        {"warehouse": w, "sku": c,
         "on_hand": on_hand_override.get((w, c), rng.randint(80, 500)), "safety_stock": safety[c]}
        for w in WAREHOUSES for c in sku_codes
    ]

    transfer_costs = []
    for (a, b), (cost, days) in _TRANSFER.items():
        for src, dst in ((a, b), (b, a)):
            transfer_costs.append({"from_warehouse": src, "to_warehouse": dst,
                                   "cost_per_unit": _money(cost), "transit_days": days})

    customers = [
        {"name": name, "city": city, "tier": tier, "allows_partial": name in PARTIAL_OK}
        for name, city, tier in CUSTOMERS
    ]
    by_tier: dict[str, list[str]] = {}
    for c in customers:
        by_tier.setdefault(c["tier"], []).append(c["name"])
    tier_of = {c["name"]: c["tier"] for c in customers}

    orders: list[dict] = []

    def add_order(ref: str, customer: str, order_offset: int, due_offset: int, lines: list[tuple[str, str, int]]):
        tier = tier_of[customer]
        value = sum(Decimal(q) * sku_cost[s] * _VALUE_MARKUP for _, s, q in lines)
        orders.append({
            "ref": ref, "customer": customer,
            "order_date": today + timedelta(days=order_offset), "due_date": today + timedelta(days=due_offset),
            "status": "open", "sla_penalty": _money(rng.choice(_PENALTY[tier])), "value": _money(value),
            "lines": [{"sku": s, "warehouse": w, "qty": q} for w, s, q in lines],
        })

    # Scenario 1: seven Chennai orders that all depend on the SHP-1042 delivery (supply 40 + 260 = 300; 235 demand leaves 65, above any safety stock)
    s1 = [("Sundaram Auto Parts", 4, 45), ("Marina Engineering Works", 5, 30), ("Adyar Packaging Co", 6, 25),
          ("Kaveri Appliances", 7, 35), ("Lalbagh Electronics", 8, 30), ("Whitefield Tools", 9, 20),
          ("Western Grid Industries", 12, 50)]
    for i, (cust, due, qty) in enumerate(s1, start=1):
        add_order(f"ORD-5{i:03d}", cust, -rng.randint(1, 4), due, [(S1_WAREHOUSE, S1_SKU, qty)])

    # Scenario 2: five Mumbai orders that depend on the SHP-1077 delivery (supply 60 + 400 = 460 >= 340)
    s2 = [("Western Grid Industries", 3, 60), ("Konkan Fabricators", 5, 70), ("Thane Hardware Mart", 7, 80),
          ("Sundaram Auto Parts", 9, 70), ("Yamuna Switchgear", 11, 60)]
    for i, (cust, due, qty) in enumerate(s2, start=1):
        add_order(f"ORD-6{i:03d}", cust, -rng.randint(1, 4), due, [(S2_WAREHOUSE, S2_SKU, qty)])

    # Background orders: small quantities on cells the scenarios do not use, never more than half the stock
    cust_names = [c["name"] for c in customers]
    stock = {(i["warehouse"], i["sku"]): i["on_hand"] for i in inventory}
    booked: dict[tuple[str, str], int] = {}
    for i in range(1, 49):
        lines, used = [], set()
        for _ in range(rng.randint(1, 3)):
            cell = (rng.choice(WAREHOUSES), rng.choice(sku_codes))
            qty = rng.randint(5, 40)
            if cell in used or cell in SCENARIO_CELLS or booked.get(cell, 0) + qty > stock[cell] // 2:
                continue
            used.add(cell)
            booked[cell] = booked.get(cell, 0) + qty
            lines.append((cell[0], cell[1], qty))
        if not lines:  # keep every order non-empty with a small line on a quiet cell
            cell = next(c for c in sorted(stock) if c not in SCENARIO_CELLS and booked.get(c, 0) + 5 <= stock[c] // 2)
            booked[cell] = booked.get(cell, 0) + 5
            lines = [(cell[0], cell[1], 5)]
        add_order(f"ORD-1{i:03d}", rng.choice(cust_names), -rng.randint(1, 10), rng.randint(5, 25), lines)

    # Shipments: the two scenario shipments plus 13 ordinary inbound ones
    shipments: list[dict] = [
        {"ref": S1_SHIPMENT, "supplier": S1_SUPPLIER, "carrier": "SeaLink Logistics", "dest_warehouse": S1_WAREHOUSE,
         "promised_eta": _eta(today, 3), "current_eta": _eta(today, 3), "status": "in_transit", "last_seq": 0,
         "lines": [{"sku": S1_SKU, "qty_expected": 260}]},
        {"ref": S2_SHIPMENT, "supplier": S2_SUPPLIER, "carrier": "RoadRunner Freight", "dest_warehouse": S2_WAREHOUSE,
         "promised_eta": _eta(today, 2), "current_eta": _eta(today, 2), "status": "in_transit", "last_seq": 0,
         "lines": [{"sku": S2_SKU, "qty_expected": 400}]},
    ]
    refs = sorted(rng.sample([r for r in range(1030, 1100) if r not in (1042, 1077)], 13))
    for r in refs:
        sku = rng.choice([c for c in sku_codes if c not in (S1_SKU, S2_SKU)])
        dest = rng.choice([w for w in WAREHOUSES if (w, sku) not in SCENARIO_CELLS])
        days = rng.randint(1, 14)
        shipments.append({
            "ref": f"SHP-{r}", "supplier": primary_of[sku], "carrier": rng.choice(CARRIERS),
            "dest_warehouse": dest, "promised_eta": _eta(today, days), "current_eta": _eta(today, days),
            "status": "in_transit", "last_seq": 0, "lines": [{"sku": sku, "qty_expected": rng.randint(60, 300)}],
        })

    return {
        "warehouses": [{"name": w, "city": w} for w in WAREHOUSES],
        "suppliers": suppliers, "skus": skus, "supplier_items": supplier_items, "inventory": inventory,
        "transfer_costs": transfer_costs, "customers": customers, "orders": orders, "shipments": shipments,
    }
