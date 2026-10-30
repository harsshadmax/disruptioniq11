import type { ApiPlan, Disruption } from "@/lib/types";

/** How many of the at-risk orders the recommended plan saves. Both numbers come from the backend. */
export function coverage(d: Disruption): { plan: ApiPlan | undefined; saved: number; total: number; pct: number | null } {
  const plan = d.planList.find((p) => p.recommended && p.feasible);
  const total = d.orders.length;
  const saved = plan ? Math.min(plan.metrics.orders_saved, total) : 0;
  return { plan, saved, total, pct: plan && total > 0 ? Math.round((saved / total) * 100) : null };
}
