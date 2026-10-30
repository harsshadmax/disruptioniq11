"""The four recovery option generators (blueprint 7.5). Each is pure and returns an OptionResult,
feasible or not. Infeasible options are returned with their reasons, never dropped.

Each generator accepts optional overrides (a reviewer changing the quantity, source, supplier, days or
orders). The same function re-evaluates a plan after a modification and re-checks it before execution,
so there is one definition of what an option does and what it is worth.
"""
from datetime import date

from app.enums import PlanType
from app.impact.allocation import Supply
from app.options.base import (
    ALT_FIXED_FEE, EXPEDITE_DAYS, EXPEDITE_FEE_RATE, MIN_TRANSIT_DAYS, SPLIT_FEE, OptionContext, OptionResult, day,
    evaluate, infeasible, plus,
)

# which plan params a reviewer may change, per plan type (anything else is rejected)
MODIFIABLE = {
    PlanType.REALLOCATE: {"qty", "source_warehouse_id"},
    PlanType.EXPEDITE: {"days_saved"},
    PlanType.ALT_SUPPLIER: {"qty", "supplier_id"},
    PlanType.SPLIT: {"order_refs"},
}


def _none_at_risk(ctx: OptionContext, t: str) -> OptionResult | None:
    return infeasible(t, ["No order is at risk, so there is nothing to recover"]) if not ctx.at_risk else None


def reallocate(ctx: OptionContext, *, qty: int | None = None, source_warehouse_id: int | None = None) -> OptionResult:
    if (r := _none_at_risk(ctx, PlanType.REALLOCATE)):
        return r
    shortfall, considered, best = ctx.shortfall, [], None
    for wh_id, sib in sorted(ctx.sibling_cells.items()):
        if source_warehouse_id is not None and wh_id != source_warehouse_id:
            continue
        name = ctx.warehouse_names[wh_id]
        lane = ctx.transfers.get((wh_id, ctx.cell.warehouse_id))
        committed = sum(ln.qty for ln in sib.lines)
        surplus = sib.on_hand - committed - sib.safety_stock
        row = {"warehouse": name, "warehouse_id": wh_id, "on_hand": sib.on_hand, "committed": committed,
               "safety_stock": sib.safety_stock, "surplus": max(surplus, 0), "feasible": False, "reason": None}
        move = qty if qty is not None else min(shortfall, surplus)
        if lane is None:
            row["reason"] = f"no transfer lane from {name} to {ctx.wh_name}"
        elif surplus <= 0:
            row["reason"] = (f"{name} has no surplus: {sib.on_hand} on hand, {committed} committed to its own orders, "
                             f"{sib.safety_stock} kept as safety stock")
        elif move > surplus:
            row["reason"] = f"{move} units requested but {name} can spare only {surplus}"
        else:
            cost_unit, transit = lane
            arrival = plus(ctx.today, transit)
            alloc = ctx.rerun(ctx.current_supply() + [Supply(arrival, move)])
            m = evaluate(ctx, alloc, cost=move * cost_unit, new_eta=arrival, stock_left=sib.on_hand - move)
            if m["orders_saved"] == 0:
                row["reason"] = f"{move} units arriving {day(arrival)} would not save any order"
            else:
                row.update(feasible=True, qty=move, cost=m["cost"], orders_saved=m["orders_saved"])
                if best is None or (m["net_benefit"], -m["cost"]) > (best[1]["net_benefit"], -best[1]["cost"]):
                    best = (wh_id, m, move, cost_unit, transit, arrival, name)
        considered.append(row)
    if best is None:
        return infeasible(PlanType.REALLOCATE, [r["reason"] for r in considered] or ["No other warehouse stocks this SKU"],
                          {"considered": considered})
    wh_id, m, move, cost_unit, transit, arrival, name = best
    params = {"source_warehouse": name, "source_warehouse_id": wh_id, "dest_warehouse": ctx.wh_name,
              "dest_warehouse_id": ctx.cell.warehouse_id, "sku": ctx.sku_code, "qty": move, "cost_per_unit": cost_unit,
              "transit_days": transit, "arrival": arrival.isoformat(), "considered": considered}
    notes = [] if move >= shortfall else [f"Only {move} of the {shortfall} units short are covered"]
    return OptionResult(PlanType.REALLOCATE, True, notes, params, m, [
        f"Pick and pack {move} x {ctx.sku_code} at {name}", f"Ship to {ctx.wh_name} ({transit} day transit)",
        f"Receive at {ctx.wh_name} and update stock", "Release the at-risk orders for picking"])


def expedite(ctx: OptionContext, *, days_saved: int | None = None) -> OptionResult:
    if (r := _none_at_risk(ctx, PlanType.EXPEDITE)):
        return r
    open_ships = [ib for ib in ctx.cell.inbound if ib.qty_expected > ib.qty_received]
    ib = ctx.trigger if ctx.trigger in open_ships else (max(open_ships, key=lambda i: i.current_eta) if open_ships else None)
    if ib is None:
        return infeasible(PlanType.EXPEDITE, ["No inbound shipment is open for this SKU at this warehouse"])
    remaining = ib.qty_expected - ib.qty_received
    current = ib.current_eta.date()
    asked = days_saved if days_saved is not None else EXPEDITE_DAYS
    new = max(plus(ctx.today, MIN_TRANSIT_DAYS), plus(current, -min(asked, EXPEDITE_DAYS)))
    saved_days = (current - new).days
    params = {"shipment_ref": ib.ref, "shipment_id": ib.shipment_id, "carrier": ib.carrier, "qty": remaining,
              "current_eta": current.isoformat(), "new_eta": new.isoformat(), "days_saved": saved_days,
              "fee_per_unit": round(ctx.unit_cost * EXPEDITE_FEE_RATE, 2)}
    if asked > EXPEDITE_DAYS:
        return infeasible(PlanType.EXPEDITE, [f"The carrier can take off at most {EXPEDITE_DAYS} days, {asked} requested"], params)
    if saved_days <= 0:
        return infeasible(PlanType.EXPEDITE, [f"{ib.ref} is already due {day(current)}, the earliest it can arrive"], params)
    alloc = ctx.rerun(ctx.current_supply({ib.shipment_id: new}))
    m = evaluate(ctx, alloc, cost=remaining * ctx.unit_cost * EXPEDITE_FEE_RATE, new_eta=new)
    if m["orders_saved"] == 0:
        return infeasible(PlanType.EXPEDITE, [f"Arriving {day(new)} instead of {day(current)} would not save any order"], params)
    return OptionResult(PlanType.EXPEDITE, True, [], params, m, [
        f"Ask {ib.carrier} to expedite {ib.ref} ({remaining} x {ctx.sku_code})",
        f"Confirm the new ETA of {day(new)} with the carrier", "Update the shipment ETA when the carrier confirms",
        "Release the at-risk orders for picking"])


def alt_supplier(ctx: OptionContext, *, qty: int | None = None, supplier_id: int | None = None) -> OptionResult:
    if (r := _none_at_risk(ctx, PlanType.ALT_SUPPLIER)):
        return r
    shortfall = ctx.shortfall
    trigger_supplier = ctx.trigger.supplier_id if ctx.trigger else None
    current_price = next((o.unit_price for o in ctx.offers if o.supplier_id == trigger_supplier), ctx.unit_cost)
    ref_eta = ctx.trigger.current_eta.date() if ctx.trigger else None
    considered, best = [], None
    for o in sorted(ctx.offers, key=lambda o: o.name):
        if o.supplier_id == trigger_supplier or (supplier_id is not None and o.supplier_id != supplier_id):
            continue
        arrival = plus(ctx.today, o.lead_days)
        buy = qty if qty is not None else shortfall
        row = {"supplier": o.name, "supplier_id": o.supplier_id, "reliability": o.reliability,
               "unit_price": o.unit_price, "lead_days": o.lead_days, "arrival": arrival.isoformat(),
               "feasible": False, "reason": None}
        if ref_eta is not None and arrival >= ref_eta:
            row["reason"] = f"{o.name} delivers {day(arrival)}, not before the delayed ETA of {day(ref_eta)}"
        else:
            cost = max(0.0, buy * (o.unit_price - current_price)) + ALT_FIXED_FEE
            alloc = ctx.rerun(ctx.current_supply() + [Supply(arrival, buy)])
            m = evaluate(ctx, alloc, cost=cost, new_eta=arrival)
            if m["orders_saved"] == 0:
                row["reason"] = f"{o.name} delivering {day(arrival)} would not save any order"
            else:
                row.update(feasible=True, cost=m["cost"], orders_saved=m["orders_saved"])
                key = (o.reliability, -m["cost"])  # procurement prefers reliable first, then cheap
                if best is None or key > best[0]:
                    best = (key, o, m, buy, arrival)
        considered.append(row)
    if best is None:
        return infeasible(PlanType.ALT_SUPPLIER, [r["reason"] for r in considered] or
                          ["No other supplier is listed for this SKU"], {"considered": considered})
    _, o, m, buy, arrival = best
    params = {"supplier": o.name, "supplier_id": o.supplier_id, "sku": ctx.sku_code, "qty": buy,
              "unit_price": o.unit_price, "current_price": round(current_price, 2), "lead_days": o.lead_days,
              "arrival": arrival.isoformat(), "fixed_fee": ALT_FIXED_FEE, "considered": considered}
    return OptionResult(PlanType.ALT_SUPPLIER, True, [], params, m, [
        f"Request a quote and delivery commitment from {o.name}", f"Place a purchase order for {buy} x {ctx.sku_code}",
        f"Confirm delivery by {day(arrival)}", f"Receive at {ctx.wh_name} and release the at-risk orders"])


def split_orders(ctx: OptionContext, *, order_refs: list[str] | None = None) -> OptionResult:
    if (r := _none_at_risk(ctx, PlanType.SPLIT)):
        return r
    lines, skipped, extra = [], [], set()
    for ln in ctx.at_risk:
        a = ctx.analysis.after[ln.line_id]
        if order_refs is not None and ln.order_ref not in order_refs:
            skipped.append(f"{ln.order_ref}: left out by the reviewer")
        elif not ln.allows_partial:
            skipped.append(f"{ln.order_ref}: {ln.customer} does not accept partial shipments")
        elif a.covered_qty <= 0:
            skipped.append(f"{ln.order_ref}: no stock available now to ship a first part")
        else:
            extra.add(ln.line_id)
            lines.append({"order_ref": ln.order_ref, "customer": ln.customer, "ship_now": a.covered_qty,
                          "remainder": a.uncovered_qty,
                          "remainder_date": a.earliest_fulfil.isoformat() if a.earliest_fulfil else None})
    params = {"lines": lines, "skipped": skipped, "order_refs": [x["order_ref"] for x in lines]}
    if not lines:
        return infeasible(PlanType.SPLIT, skipped or ["No at-risk order can be split"], params)
    dates = [date.fromisoformat(x["remainder_date"]) for x in lines if x["remainder_date"]]
    m = evaluate(ctx, None, cost=SPLIT_FEE * len(lines), new_eta=max(dates) if dates else None, extra_saved=extra)
    return OptionResult(PlanType.SPLIT, True, skipped, params, m, [
        f"Ship the available part of {len(lines)} order(s) now", "Notify the customers of the split delivery",
        "Ship each remainder when new supply arrives", "Close the orders when the remainder is delivered"])


GENERATORS = (reallocate, expedite, alt_supplier, split_orders)
_BY_TYPE = {PlanType.REALLOCATE: reallocate, PlanType.EXPEDITE: expedite, PlanType.ALT_SUPPLIER: alt_supplier,
            PlanType.SPLIT: split_orders}


def recompute_option(ctx: OptionContext, plan_type: str, **overrides) -> OptionResult:
    """Evaluate one option type with explicit parameters (modification, or pre-execution re-check)."""
    return _BY_TYPE[PlanType(plan_type)](ctx, **overrides)


def overrides_from_params(plan_type: str, params: dict) -> dict:
    """The reviewer-controlled parameters of a stored plan, to re-evaluate it exactly as approved."""
    t = PlanType(plan_type)
    if t == PlanType.REALLOCATE:
        return {"qty": params["qty"], "source_warehouse_id": params["source_warehouse_id"]}
    if t == PlanType.EXPEDITE:
        return {"days_saved": params["days_saved"]}
    if t == PlanType.ALT_SUPPLIER:
        return {"qty": params["qty"], "supplier_id": params["supplier_id"]}
    return {"order_refs": params.get("order_refs", [])}


def generate_options(ctx: OptionContext) -> list[OptionResult]:
    """All four options, best first: feasible by net benefit, then orders saved, then lower cost; infeasible last."""
    results = [g(ctx) for g in GENERATORS]
    results.sort(key=lambda r: (not r.feasible, -r.metrics["net_benefit"], -r.metrics["orders_saved"], r.metrics["cost"]))
    return results
