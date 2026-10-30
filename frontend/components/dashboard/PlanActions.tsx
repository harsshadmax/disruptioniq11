"use client";

import { inr, planTitle, statusLabel } from "@/lib/adapt";
import { PlanControls } from "@/components/plans/PlanControls";
import type { Disruption } from "@/lib/types";

const IN_PROGRESS = ["PROPOSED", "APPROVED", "EXECUTING"];
const STATUS_TONE: Record<string, string> = {
  DRAFT: "bg-[#eef0f3] text-[#555]",
  PROPOSED: "bg-[#fff1e3] text-[#d9741a]",
  APPROVED: "bg-[#e3ecff] text-[#3b6fe0]",
  COMPLETED: "bg-[#e6f6ea] text-[#16a34a]",
  REJECTED: "bg-[#fdecee] text-[#e5384f]",
  STALE: "bg-[#fdecee] text-[#e5384f]",
};

/** Compact plan list for the dashboard card. The buttons are the same PlanControls the plans page uses. */
export function PlanActions({ d, role }: { d: Disruption; role: string }) {
  const inFlight = d.planList.some((p) => IN_PROGRESS.includes(p.status));
  return (
    <div className="rounded-2xl bg-white p-5 border border-[#e6e8ec]">
      <div className="mb-3 flex items-baseline justify-between">
        <div className="text-base font-bold text-[#1c1c1e]">Recovery plans</div>
        <div className="text-[10px] text-[#8a8a8f]">Rules build and rank the options. People approve.</div>
      </div>
      <ul className="space-y-2">
        {d.planList.map((p) => (
          <li key={p.id} className={`rounded-xl border p-3 ${p.recommended ? "border-brand-edge bg-brand-wash" : "border-[#eeeef0]"}`}>
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-xs font-semibold text-[#1c1c1e]">{planTitle(p)}</span>
              {p.recommended && <span className="rounded-md bg-brand-soft px-1.5 py-0.5 text-[9px] font-semibold text-brand">Recommended</span>}
              <span className={`ml-auto rounded-md px-2 py-0.5 text-[10px] font-semibold ${STATUS_TONE[p.status] ?? STATUS_TONE.DRAFT}`}>{statusLabel(p.status)}</span>
            </div>
            {p.feasible ? (
              <div className="mt-1.5 flex flex-wrap gap-x-4 gap-y-1 text-[11px] text-[#6b6b70]">
                <span>Cost <b className="text-[#1c1c1e]">{inr(p.metrics.cost)}</b></span>
                <span>Saves <b className="text-[#1c1c1e]">{p.metrics.orders_saved}</b> of {d.orders.length} orders</span>
                <span>Penalty avoided <b className="text-[#1c1c1e]">{inr(p.metrics.penalty_avoided)}</b></span>
                <span>Net <b className={p.metrics.net_benefit >= 0 ? "text-[#16a34a]" : "text-[#e5384f]"}>{inr(p.metrics.net_benefit)}</b></span>
              </div>
            ) : (
              <div className="mt-1.5 text-[11px] text-[#9b1c2e]">Not feasible: {p.reasons.slice(0, 2).join("; ")}{p.reasons.length > 2 ? ` (+${p.reasons.length - 2} more)` : ""}</div>
            )}
            <div className="mt-2">
              <PlanControls plan={p} role={role} inFlight={inFlight} />
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}
