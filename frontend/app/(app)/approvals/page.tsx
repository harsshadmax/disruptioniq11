"use client";

import Link from "next/link";
import { useState } from "react";
import { useAuth } from "@/lib/auth";
import { usePlans } from "@/lib/queries";
import { planTitle, statusLabel } from "@/lib/adapt";
import type { Plan } from "@/lib/api/types";
import { PlanControls } from "@/components/plans/PlanControls";
import { Empty, ErrorBox, inr, PageTitle, Panel, Pill, STATUS_TONE, when } from "@/components/ui/bits";

type Tab = "approve" | "execute" | "all";
const DONE = ["COMPLETED", "REJECTED", "STALE"];

export default function ApprovalsPage() {
  const { user } = useAuth();
  const role = user?.role ?? "";
  const [tab, setTab] = useState<Tab>("approve");
  const all = usePlans();
  if (all.error) return <ErrorBox error={all.error} onRetry={() => all.refetch()} />;

  const plans = all.data ?? [];
  const mine: Record<Tab, Plan[]> = {
    approve: plans.filter((p) => p.status === "PROPOSED" && p.approver_roles.includes(role)),
    execute: plans.filter((p) => p.status === "APPROVED" && p.executor_roles.includes(role)),
    all: plans,
  };
  const inFlight = (p: Plan) => plans.some((q) => q.disruption_id === p.disruption_id && ["PROPOSED", "APPROVED", "EXECUTING"].includes(q.status));
  const rows = mine[tab];
  const TABS: [Tab, string][] = [["approve", "Awaiting my approval"], ["execute", "Ready for me to confirm"], ["all", "All plans"]];

  return (
    <>
      <PageTitle title="Approvals" sub="Plans that need a person. You never approve your own proposal or a plan you changed." />
      <div className="flex gap-2" role="tablist">
        {TABS.map(([k, label]) => (
          <button key={k} role="tab" aria-selected={tab === k} onClick={() => setTab(k)}
            className={`rounded-lg px-4 py-2 text-xs font-medium ${tab === k ? "bg-[#1b2430] text-white" : "bg-white text-[#2f3944] border border-[#ddd9d0]"}`}>
            {label} ({mine[k].length})
          </button>
        ))}
      </div>
      {all.isLoading && <div className="h-48 animate-pulse rounded-2xl bg-white" />}
      {all.data && rows.length === 0 && (
        <Empty>{tab === "approve" ? "Nothing is waiting for your approval." : tab === "execute" ? "Nothing is waiting for you to confirm." : "No plans yet."}</Empty>
      )}
      <div className="grid gap-3">
        {rows.map((p) => {
          const m = p.metrics as Record<string, number>;
          return (
            <Panel key={p.id}>
              <div className="flex flex-wrap items-center gap-2">
                <span className="text-sm font-bold">Plan #{p.id}: {planTitle(p)}</span>
                <Pill tone={STATUS_TONE[p.status]}>{statusLabel(p.status)}</Pill>
                {p.overdue && <Pill tone="bg-[#f8e4e1] text-[#c8352b]">overdue</Pill>}
                <Link href={`/disruptions/${p.disruption_id}/plans`} className="ml-auto text-xs text-brand">{p.warehouse} · {p.sku_code} · DIS-{p.disruption_id}</Link>
              </div>
              {p.feasible && (
                <p className="mt-2 text-xs text-[#4a545e]">
                  Cost <b>{inr(m.cost)}</b> · saves <b>{m.orders_saved}</b> orders · avoids <b>{inr(m.penalty_avoided)}</b> in penalties · net <b>{inr(m.net_benefit)}</b>
                </p>)}
              {p.ai_rationale && <p className="mt-2 text-[11px] text-[#5c6670]">AI note: {p.ai_rationale}</p>}
              <p className="mt-1 text-[10px] text-[#6b7480]">Last change {when(p.updated_at)} · version {p.version}</p>
              {!DONE.includes(p.status) && <div className="mt-3"><PlanControls plan={p} role={role} inFlight={inFlight(p)} /></div>}
            </Panel>
          );
        })}
      </div>
    </>
  );
}
