// Backend response shapes (subset the dashboard uses) and the view model the components render.

export type Band = "high" | "medium" | "low" | "info";

export interface ApiUser {
  id: number;
  name: string;
  email: string;
  role: string;
  warehouse_id: number | null;
}

export interface ApiDisruption {
  id: number;
  type: string;
  severity: string;
  status: string;
  detected_at: string;
  summary: string | null;
  warehouse: string;
  sku_code: string;
  sku_name: string;
  shipment_ref: string | null;
  supplier: string | null;
  orders_at_risk: number;
  newly_at_risk: number;
  penalty_exposure: number;
}

export interface ApiDisruptionDetail extends ApiDisruption {
  promised_eta: string | null;
  current_eta: string | null;
}

export interface ApiRankedOrder {
  rank: number;
  order_id: number;
  order_ref: string;
  customer: string;
  tier: string;
  due_date: string;
  score: number;
  band: string;
  newly_at_risk: boolean;
  uncovered_qty: number;
  order_qty: number;
  sla_penalty: number;
}

export interface ApiPlan {
  id: number;
  disruption_id: number;
  type: string;
  status: string;
  version: number;
  feasible: boolean;
  recommended: boolean;
  ai_rationale: string | null;
  overdue: boolean;
  params: Record<string, unknown>;
  metrics: {
    cost: number;
    net_benefit: number;
    penalty_avoided: number;
    orders_saved: number;
    new_eta: string | null;
  };
  reasons: string[];
  steps: { seq: number; description: string; status: string }[];
  approver_roles: string[];
  executor_roles: string[];
  updated_at: string;
}

export interface ApiInbox {
  unread: number;
}

export interface ApiTextOut {
  text: string;
  source: string;
}

export interface ApiDetection {
  created: number[];
  updated: number[];
  resolved: number[];
  unchanged: number[];
}

// ---- view model ----

export interface RippleNode {
  id: string;
  label: string;
  sub?: string;
  band: Band;
  col: number;
  row: number;
  /** Set on order nodes: the order's database id, used to link to its detail. */
  orderId?: number;
}

export interface TimelineStep {
  title: string;
  detail: string;
  when: string;
  state: "done" | "current" | "pending";
}

export interface PlanOption {
  name: string;
  cost: number; // INR thousands
  penaltyAvoided: number; // INR thousands
  ordersSaved: number;
}

export interface Disruption {
  id: string;
  dbId: number;
  ref: string;
  title: string;
  type: "Late shipment" | "Supplier delay" | "Stock shortage";
  severity: Band;
  warehouse: string;
  supplier: string;
  shipment: string | null;
  planStatus: string;
  etaChange: string;
  affectedOrders: number;
  unitsShort: number;
  penaltyExposed: string;
  bestEta: string;
  ripple: { nodes: RippleNode[]; edges: [string, string][] };
  timeline: TimelineStep[];
  aiSummary: string;
  aiSource: "ai" | "rules";
  recommended: string;
  net: string;
  metrics: { cost: string; saved: string; penalty: string };
  bands: { high: number; medium: number; low: number };
  plans: PlanOption[];
  orders: ApiRankedOrder[];
  planList: ApiPlan[];
  searchText: string;
}

export interface Kpi {
  label: string;
  value: string;
  note: string;
  good: boolean;
  tone: "green" | "red" | "orange" | "blue";
  icon: "truck" | "alert" | "clipboard" | "gauge";
}

export interface DashboardData {
  items: Disruption[];
  kpis: Kpi[];
  pendingApprovals: number;
}
