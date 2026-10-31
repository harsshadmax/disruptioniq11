import type { components } from "./schema";

type S = components["schemas"];

export type Disruption = S["DisruptionOut"];
export type DisruptionDetail = S["DisruptionDetail"];
export type ImpactLine = S["ImpactLine"];
export type RankedOrder = S["RankedOrder"];
export type RiskFactor = S["RiskFactor"];
export type Plan = S["PlanOut"];
export type ImportResult = S["ImportResult"];
export type Notification = S["NotificationOut"];
export type Inbox = S["Inbox"];
export type AiText = S["TextOut"];
export type AiRecommendation = S["RecommendationOut"];
export type AiStatus = S["AiStatus"];
export type DemoResult = S["DemoResult"];
export type DemoTargets = S["DemoTargets"];
export type DetectionResult = S["DetectionResult"];
export type User = S["UserOut"];
export type SimulationOptions = S["SimulationOptions"];
export type SimulationResult = S["SimulationOut"];
export type SimulationOrder = S["OrderRow"];
export type SimulationWarehouse = S["WarehouseRow"];
export type SimulationMetrics = S["MetricsOut"];
export type Contract = S["ContractOut"];
export type ContractTerms = S["Terms"];
export type ContractCustomer = S["CustomerOut"];
export type ContractPreview = S["PreviewOut"];
export type ContractConfirmResult = S["ConfirmOut"];

/** The AI second opinion on a contract's terms (the API sends it as a plain object). */
export type AiCheck =
  | { available: false; reason: string }
  | {
      available: true; provider: string; model: string | null; summary: string;
      checks: { field: string; label: string; value: number | string | boolean; verdict: "supported" | "contradicted" | "not_found" | "unverified"; quote: string }[];
      missed: { what: string; quote: string }[];
    };

/** One event of a what-if scenario, as the API expects it. */
export type ScenarioEvent =
  | { kind: "supplier_shutdown"; supplier_id: number }
  | { kind: "shipment_delay"; shipment_id: number; days: number }
  | { kind: "demand_surge"; percent: number; warehouse_id: number | null; sku_id: number | null }
  | { kind: "stock_reduction"; percent: number; warehouse_id: number | null; sku_id: number | null };

// Endpoints whose response is a plain dict on the backend, typed here by hand.
export type LoginResponse = { access_token: string; token_type: string; user: User };
export type AuditRow = {
  id: number;
  ts: string;
  actor_id: number | null;
  role: string | null;
  action: string;
  entity_type: string;
  entity_id: string | null;
  reason: string | null;
  payload: Record<string, unknown>;
  row_hash: string;
};
export type AuditVerify = { ok: boolean; first_bad_id: number | null; rows_checked: number };

export const ROLE_LABEL: Record<string, string> = {
  ops_analyst: "Operations Analyst",
  supply_chain_manager: "Supply Chain Manager",
  warehouse_operator: "Warehouse Operator",
  procurement_approver: "Procurement Approver",
  administrator: "Administrator",
};

// Display-only hints for hiding buttons. The backend enforces every one of these again.
export const CAN = {
  runDetection: ["ops_analyst", "supply_chain_manager", "administrator"],
  importData: ["ops_analyst", "administrator"],
  propose: ["ops_analyst"],
  modifyDraft: ["ops_analyst", "supply_chain_manager"],
  modifyProposed: ["supply_chain_manager", "procurement_approver"],
  generatePlans: ["ops_analyst", "supply_chain_manager"],
  readAudit: ["supply_chain_manager", "procurement_approver", "administrator"],
  useAi: ["ops_analyst", "supply_chain_manager", "procurement_approver"],
  simulate: ["ops_analyst", "supply_chain_manager", "procurement_approver", "administrator"],
  contractView: ["ops_analyst", "supply_chain_manager", "procurement_approver", "administrator"],
  contractUpload: ["ops_analyst", "supply_chain_manager", "administrator"],
  contractConfirm: ["supply_chain_manager"],
  demoControls: ["administrator"],
} as const;

export function allowed(list: readonly string[], role: string | undefined): boolean {
  return !!role && list.includes(role);
}
