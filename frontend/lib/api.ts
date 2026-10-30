import { api, ApiError } from "@/lib/api/client";
import { buildDashboard } from "./adapt";
import type {
  ApiDetection, ApiDisruption, ApiDisruptionDetail, ApiInbox, ApiPlan, ApiRankedOrder, ApiTextOut, ApiUser,
  DashboardData,
} from "./types";

// Dashboard-specific calls. The generic client (token handling, errors, 401 redirect) lives in lib/api/client.ts.
export { ApiError };

const post = <T,>(path: string, body?: unknown) => api<T>(path, { method: "POST", body });

export const me = () => api<ApiUser>("/auth/me");
export const notifications = () => api<ApiInbox>("/notifications", { params: { unread_only: "true", limit: 1 } });
export const runDetection = () => post<ApiDetection>("/disruptions/detect");
export const aiSummary = (disruptionId: number) => post<ApiTextOut>(`/ai/disruptions/${disruptionId}/summary`);

const planAction = (id: number, action: string, body: object) => post<ApiPlan>(`/plans/${id}/${action}`, body);

export const proposePlan = (id: number, version: number) => planAction(id, "propose", { version });
export const approvePlan = (id: number, version: number) => planAction(id, "approve", { version });
export const executePlan = (id: number, version: number) => planAction(id, "execute", { version });
export const rejectPlan = (id: number, version: number, reason: string) => planAction(id, "reject", { version, reason });

export async function loadDashboard(): Promise<DashboardData> {
  const [all, proposed] = await Promise.all([
    api<ApiDisruption[]>("/disruptions", { params: { state: "all" } }),
    api<ApiPlan[]>("/plans", { params: { state: "PROPOSED" } }),
  ]);
  const active = all.filter((d) => d.status === "active");
  const perDisruption = await Promise.all(
    active.map(async (d) => {
      const [detail, orders, plans] = await Promise.all([
        api<ApiDisruptionDetail>(`/disruptions/${d.id}`),
        api<ApiRankedOrder[]>(`/disruptions/${d.id}/orders`),
        api<ApiPlan[]>(`/disruptions/${d.id}/plans`),
      ]);
      return { detail, orders, plans };
    }),
  );
  return buildDashboard({
    perDisruption,
    totalDisruptions: all.length,
    resolvedDisruptions: all.length - active.length,
    proposedPlans: proposed,
  });
}
