// Turns backend responses into the view model. Every number shown comes from the API; this only formats and arranges.
import type {
  ApiDisruptionDetail, ApiPlan, ApiRankedOrder, Band, DashboardData, Disruption, Kpi, PlanOption, RippleNode,
  TimelineStep,
} from "./types";

export const ROLE_LABEL: Record<string, string> = {
  ops_analyst: "Operations Analyst",
  supply_chain_manager: "Supply Chain Manager",
  warehouse_operator: "Warehouse Operator",
  procurement_approver: "Procurement Approver",
  administrator: "Administrator",
};

const TYPE_LABEL: Record<string, Disruption["type"]> = {
  late_shipment: "Late shipment",
  supplier_delay: "Supplier delay",
  stock_shortage: "Stock shortage",
};

const PLAN_LABEL: Record<string, string> = {
  reallocate: "Reallocate",
  expedite: "Expedite",
  alt_supplier: "Alt supplier",
  split: "Split order",
};

const STATUS_LABEL: Record<string, string> = {
  DRAFT: "Draft",
  PROPOSED: "Awaiting approval",
  APPROVED: "Approved",
  EXECUTING: "Executing",
  COMPLETED: "Completed",
  REJECTED: "Rejected",
  STALE: "Stale",
};

// Rupees in the Indian short form: 580 -> ₹580, 45000 -> ₹45k, 149420 -> ₹1.49L.
export function inr(n: number): string {
  const sign = n < 0 ? "-" : "";
  const v = Math.abs(n);
  if (v >= 100000) return `${sign}₹${trim(v / 100000, 2)}L`;
  if (v >= 1000) return `${sign}₹${trim(v / 1000, 1)}k`;
  return `${sign}₹${Math.round(v)}`;
}

const trim = (x: number, digits: number) => String(parseFloat(x.toFixed(digits)));

const day = (iso: string) => new Date(iso).toLocaleDateString("en-GB", { day: "numeric", month: "short" });
const stamp = (iso: string) =>
  new Date(iso).toLocaleString("en-GB", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });

const band = (s: string): Band => (s === "high" || s === "medium" || s === "low" ? s : "info");
const cap = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);
const roles = (rs: string[]) => rs.map((r) => ROLE_LABEL[r] ?? r).join(" or ");

function leadPlan(plans: ApiPlan[]): ApiPlan | undefined {
  const live = plans.find((p) => !["DRAFT", "REJECTED", "STALE", "CANCELLED"].includes(p.status));
  return live ?? plans.find((p) => p.recommended) ?? plans.find((p) => p.feasible) ?? plans[0];
}

export const statusLabel = (s: string) => STATUS_LABEL[s] ?? s;
export const rolesLabel = roles;

export function planTitle(p: { type: string; params: Record<string, unknown> }): string {
  const x = p.params as Record<string, string | undefined>;
  switch (p.type) {
    case "reallocate": return `Reallocate from ${x.source_warehouse ?? "another warehouse"}`;
    case "expedite": return `Expedite with ${x.carrier ?? "the carrier"}`;
    case "alt_supplier": return `Buy from ${x.supplier ?? "an alternative supplier"}`;
    default: return "Split the orders";
  }
}

function timeline(d: ApiDisruptionDetail, lead: ApiPlan | undefined, feasible: number): TimelineStep[] {
  const cur = !lead ? 1 : { DRAFT: 2, PROPOSED: 3, APPROVED: 4, EXECUTING: 4, COMPLETED: 5 }[lead.status] ?? 2;
  const planWhen = lead ? stamp(lead.updated_at) : "Pending";
  const steps: [string, string, string][] = [
    ["Disruption detected", `${TYPE_LABEL[d.type] ?? d.type}${d.shipment_ref ? ` · ${d.shipment_ref}` : ""}`, stamp(d.detected_at)],
    ["Plans generated", `${feasible} feasible option${feasible === 1 ? "" : "s"} built by rules`, stamp(d.detected_at)],
    ["Plan proposed", lead ? (cur === 2 ? `An analyst proposes: ${planTitle(lead)}` : planTitle(lead)) : "No feasible plan yet", planWhen],
    ["Plan approved", lead ? `Needs ${roles(lead.approver_roles)}` : "", planWhen],
    ["Executed", lead ? `Done by ${roles(lead.executor_roles)}; stock and ETA update, audit logged` : "", planWhen],
  ];
  return steps.map(([title, detail, when], i) => ({
    title,
    detail,
    when: i > cur ? "Pending" : when,
    state: i < cur ? "done" : i === cur ? "current" : "pending",
  }));
}

function ripple(d: ApiDisruptionDetail, orders: ApiRankedOrder[], daysLate: number | null, unitsShort: number): Disruption["ripple"] {
  const shown = orders.slice(0, 6);
  const mid = Math.max(0, (shown.length - 1) / 2);
  const nodes: RippleNode[] = [];
  const chain: RippleNode[] = [];
  if (d.supplier) chain.push({ id: "sup", label: d.supplier, sub: "Supplier", band: "info", col: 0, row: mid });
  if (d.shipment_ref) {
    chain.push({
      id: "shp", label: d.shipment_ref, band: band(d.severity), col: 0, row: mid,
      sub: daysLate && daysLate > 0 ? `+${daysLate} days late` : d.type === "stock_shortage" ? "Partial delivery" : "Delayed",
    });
  }
  chain.push({ id: "wh", label: `${d.warehouse} WH`, sub: `${unitsShort} units short`, band: unitsShort > 0 ? "high" : "low", col: 0, row: mid });
  chain.forEach((n, i) => nodes.push({ ...n, col: i }));
  shown.forEach((o, i) =>
    nodes.push({ id: `o${i}`, label: `${o.order_ref} · ${cap(o.tier)}`, sub: `risk ${Math.round(o.score)}`, band: band(o.band), col: chain.length, row: i, orderId: o.order_id }),
  );
  const edges: [string, string][] = [];
  for (let i = 1; i < chain.length; i++) edges.push([chain[i - 1].id, chain[i].id]);
  shown.forEach((_, i) => edges.push(["wh", `o${i}`]));
  return { nodes, edges };
}

function adapt(d: ApiDisruptionDetail, orders: ApiRankedOrder[], plans: ApiPlan[]): Disruption {
  const lead = leadPlan(plans);
  const feasible = plans.filter((p) => p.feasible);
  const unitsShort = orders.reduce((s, o) => s + o.uncovered_qty, 0);
  const daysLate =
    d.promised_eta && d.current_eta ? Math.round((+new Date(d.current_eta) - +new Date(d.promised_eta)) / 86400000) : null;
  const m = lead?.metrics;
  const options: PlanOption[] = feasible.map((p) => ({
    name: PLAN_LABEL[p.type] ?? p.type,
    cost: Math.round(p.metrics.cost / 100) / 10,
    penaltyAvoided: Math.round(p.metrics.penalty_avoided / 100) / 10,
    ordersSaved: p.metrics.orders_saved,
  }));
  const text = lead?.ai_rationale ?? d.summary ?? "";
  return {
    id: `d${d.id}`,
    dbId: d.id,
    ref: `DIS-${d.id}`,
    title: d.shipment_ref ? `${TYPE_LABEL[d.type] ?? d.type}: ${d.shipment_ref}` : `${d.sku_code} at ${d.warehouse}`,
    type: TYPE_LABEL[d.type] ?? "Late shipment",
    severity: band(d.severity),
    warehouse: d.warehouse,
    supplier: d.supplier ?? "Unknown supplier",
    shipment: d.shipment_ref,
    planStatus: lead ? (STATUS_LABEL[lead.status] ?? lead.status) : "No plan",
    etaChange: d.promised_eta && d.current_eta ? `ETA ${day(d.promised_eta)} → ${day(d.current_eta)}` : `${d.sku_code} short`,
    affectedOrders: d.orders_at_risk,
    unitsShort,
    penaltyExposed: inr(d.penalty_exposure),
    bestEta: m?.new_eta ? day(m.new_eta) : d.current_eta ? day(d.current_eta) : "n/a",
    ripple: ripple(d, orders, daysLate, unitsShort),
    timeline: timeline(d, lead, feasible.length),
    aiSummary: text,
    aiSource: lead?.ai_rationale ? "ai" : "rules",
    recommended: lead ? planTitle(lead) : "No feasible plan",
    net: m ? `${m.net_benefit >= 0 ? "+" : ""}${inr(m.net_benefit)}` : "n/a",
    metrics: {
      cost: m ? inr(m.cost) : "n/a",
      saved: m ? (orders.length ? `${m.orders_saved} of ${orders.length}` : String(m.orders_saved)) : "n/a",
      penalty: m ? inr(m.penalty_avoided) : "n/a",
    },
    bands: {
      high: orders.filter((o) => o.band === "high").length,
      medium: orders.filter((o) => o.band === "medium").length,
      low: orders.filter((o) => o.band === "low").length,
    },
    plans: options,
    orders,
    planList: plans,
    searchText: [d.shipment_ref, `DIS-${d.id}`, d.sku_code, d.warehouse, ...orders.map((o) => o.order_ref)].join(" ").toLowerCase(),
  };
}

export function buildDashboard(args: {
  perDisruption: { detail: ApiDisruptionDetail; orders: ApiRankedOrder[]; plans: ApiPlan[] }[];
  totalDisruptions: number;
  resolvedDisruptions: number;
  proposedPlans: ApiPlan[];
}): DashboardData {
  const items = args.perDisruption.map((x) => adapt(x.detail, x.orders, x.plans));
  const atRisk = args.perDisruption.reduce((s, x) => s + x.detail.orders_at_risk, 0);
  const newly = args.perDisruption.reduce((s, x) => s + x.detail.newly_at_risk, 0);
  const exposure = args.perDisruption.reduce((s, x) => s + x.detail.penalty_exposure, 0);
  const pending = args.proposedPlans.length;
  const overdue = args.proposedPlans.filter((p) => p.overdue).length;
  const pct = args.totalDisruptions ? Math.round((args.resolvedDisruptions / args.totalDisruptions) * 100) : 0;
  const kpis: Kpi[] = [
    { label: "Active disruptions", value: String(items.length), note: `${inr(exposure)} at stake`, good: items.length === 0, tone: "green", icon: "truck" },
    { label: "Orders at risk", value: String(atRisk), note: `${newly} newly at risk`, good: newly === 0, tone: "red", icon: "alert" },
    { label: "Pending approvals", value: String(pending), note: overdue ? `${overdue} overdue` : "none overdue", good: overdue === 0, tone: "orange", icon: "clipboard" },
    { label: "Recovery progress", value: `${pct}%`, note: `${args.resolvedDisruptions} of ${args.totalDisruptions} resolved`, good: pct > 0, tone: "blue", icon: "gauge" },
  ];
  return { items, kpis, pendingApprovals: pending };
}
