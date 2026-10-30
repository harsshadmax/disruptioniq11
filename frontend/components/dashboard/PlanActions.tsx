"use client";

import { inr, planTitle, statusLabel } from "@/lib/adapt";
import { PlanControls } from "@/components/plans/PlanControls";
import type { Disruption } from "@/lib/types";

const IN_PROGRESS = ["PROPOSED", "APPROVED", "EXECUTING"];
const STATUS_TONE: Record<string, string> = {
  DRAFT: "bg-[#ece9e2] text-[#555]",
  PROPOSED: "bg-[#f8ecd3] text-[#c77700]",
  APPROVED: "bg-[#e3ecff] text-[#3b6fe0]",
  COMPLETED: "bg-[#e3f0e7] text-[#2e7d4f]",
  REJECTED: "bg-[#f8e4e1] text-[#c8352b]",
  STALE: "bg-[#f8e4e1] text-[#c8352b]",
};

/** Compact plan list for the dashboard card. The buttons are the same PlanControls the plans page uses. */
export function PlanActions({ d, role }: { d: Disruption; role: string }) {
  const inFlight = d.planList.some((p) => IN_PROGRESS.includes(p.status));
  return (
    <div className="rounded-2xl bg-white p-5 border border-[#ddd9d0]">
      <div className="mb-3 flex items-baseline justify-between">
        <div className="text-base font-bold text-[#1b2430]">Recovery plans</div>
        <div className="text-[10px] text-[#6b7480]">Rules build and rank the options. People approve.</div>
      </div>
      <ul className="space-y-2">
        {d.planList.map((p) => (
          <li key={p.id} className={`rounded-xl border p-3 ${p.recommended ? "border-brand-edge bg-brand-wash" : "border-[#ece9e2]"}`}>
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-xs font-semibold text-[#1b2430]">{planTitle(p)}</span>
              {p.recommended && <span className="rounded-md bg-brand-soft px-1.5 py-0.5 text-[9px] font-semibold text-brand">Recommended</span>}
              <span className={`ml-auto rounded-md px-2 py-0.5 text-[10px] font-semibold ${STATUS_TONE[p.status] ?? STATUS_TONE.DRAFT}`}>{statusLabel(p.status)}</span>
            </div>
            {p.feasible ? (
              <div className="mt-1.5 flex flex-wrap gap-x-4 gap-y-1 text-[11px] text-[#5c6670]">
                <span>Cost <b className="text-[#1b2430]">{inr(p.metrics.cost)}</b></span>
                <span>Saves <b className="text-[#1b2430]">{p.metrics.orders_saved}</b> of {d.orders.length} orders</span>
                <span>Penalty avoided <b className="text-[#1b2430]">{inr(p.metrics.penalty_avoided)}</b></span>
                <span>Net <b className={p.metrics.net_benefit >= 0 ? "text-[#2e7d4f]" : "text-[#c8352b]"}>{inr(p.metrics.net_benefit)}</b></span>
              </div>
            ) : (
              <div className="mt-1.5 text-[11px] text-[#8c2a22]">Not feasible: {p.reasons.slice(0, 2).join("; ")}{p.reasons.length > 2 ? ` (+${p.reasons.length - 2} more)` : ""}</div>
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
