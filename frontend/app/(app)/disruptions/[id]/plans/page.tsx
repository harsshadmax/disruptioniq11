"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, Loader2, RefreshCw, Sparkles } from "lucide-react";
import { api } from "@/lib/api/client";
import { allowed, CAN, type AiRecommendation } from "@/lib/api/types";
import { useAuth } from "@/lib/auth";
import { useDisruption, useDisruptionPlans } from "@/lib/queries";
import { planTitle, rolesLabel, statusLabel } from "@/lib/adapt";
import { PlanControls } from "@/components/plans/PlanControls";
import { btnOutline, btnPrimary, dayOf, Empty, ErrorBox, inr, PageTitle, Panel, Pill, STATUS_TONE } from "@/components/ui/bits";

const IN_PROGRESS = ["PROPOSED", "APPROVED", "EXECUTING"];

export default function PlansPage() {
  const id = Number(useParams<{ id: string }>().id);
  const { user } = useAuth();
  const role = user?.role ?? "";
  const qc = useQueryClient();
  const d = useDisruption(id);
  const plans = useDisruptionPlans(id);

  const recommend = useMutation({
    mutationFn: () => api<AiRecommendation>(`/ai/disruptions/${id}/recommend`, { method: "POST" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["plans", "of", id] }),
  });
  const regenerate = useMutation({
    mutationFn: () => api(`/disruptions/${id}/plans/generate`, { method: "POST" }),
    onSuccess: () => qc.invalidateQueries(),
  });

  if (plans.error) return <ErrorBox error={plans.error} onRetry={() => plans.refetch()} />;
  if (!plans.data || !d.data) return <div className="h-96 animate-pulse rounded-2xl bg-white" />;
  const list = plans.data;
  const inFlight = list.some((p) => IN_PROGRESS.includes(p.status));
  const best = Math.max(...list.filter((p) => p.feasible).map((p) => p.metrics.net_benefit as number), -Infinity);
  const aiPick = recommend.data;

  return (
    <>
      <PageTitle
        title="Recovery plans"
        sub={<Link href={`/disruptions/${id}`} className="inline-flex items-center gap-1 text-[#e5384f]"><ArrowLeft className="size-3" /> DIS-{id} · {d.data.warehouse} · {d.data.sku_code}</Link>}
        actions={<>
          {allowed(CAN.generatePlans, role) && d.data.status === "active" && (
            <button onClick={() => regenerate.mutate()} disabled={regenerate.isPending || inFlight} title={inFlight ? "A plan is in progress" : "Recompute the draft options"} className={btnOutline}>
              {regenerate.isPending ? <Loader2 className="size-3.5 animate-spin" /> : <RefreshCw className="size-3.5" />} Recompute options
            </button>)}
          {allowed(CAN.useAi, role) && (
            <button onClick={() => recommend.mutate()} disabled={recommend.isPending} className={btnPrimary}>
              {recommend.isPending ? <Loader2 className="size-3.5 animate-spin" /> : <Sparkles className="size-3.5" />} Ask AI to recommend
            </button>)}
        </>}
      />
      {recommend.error && <p role="alert" className="text-xs text-[#e5384f]">{(recommend.error as Error).message}</p>}
      {regenerate.error && <p role="alert" className="text-xs text-[#e5384f]">{(regenerate.error as Error).message}</p>}
      {aiPick && (
        <Panel title={`${aiPick.source === "ai" ? "AI" : "Rule-based"} recommendation: plan #${aiPick.plan_id}`}
          aside={aiPick.source === "ai" ? "Choice and numbers checked against the options below" : `Template (${aiPick.fallback_reason ?? "AI off"})`}>
          <p className="text-sm leading-relaxed">{aiPick.rationale}</p>
          <p className="mt-2 text-[10px] text-[#8a8a8f]">Advice only. Someone with the right role still has to approve it.</p>
        </Panel>
      )}
      {list.length === 0 && <Empty>No plans yet for this disruption.</Empty>}

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        {list.map((p) => {
          const m = p.metrics as Record<string, number>;
          const top = p.feasible && m.net_benefit === best;
          return (
            <section key={p.id} className={`flex flex-col rounded-2xl bg-white p-4 shadow-sm ${p.recommended ? "ring-2 ring-[#f2c9ce]" : ""}`}>
              <div className="flex flex-wrap items-center gap-1.5">
                <h2 className="text-sm font-bold text-[#1c1c1e]">{planTitle(p)}</h2>
                {p.recommended && <Pill tone="bg-[#fdecee] text-[#e5384f]">Recommended</Pill>}
                {aiPick?.plan_id === p.id && <Pill tone="bg-[#f1e6ff] text-[#7a3fd1]">AI pick</Pill>}
              </div>
              <div className="mt-1"><Pill tone={STATUS_TONE[p.status]}>{statusLabel(p.status)}</Pill>{p.overdue && <span className="ml-2 text-[10px] font-semibold text-[#e5384f]">overdue</span>}</div>

              {p.feasible ? (
                <dl className="mt-3 grid grid-cols-2 gap-2 text-xs">
                  {[["Cost", inr(m.cost)], ["Orders saved", `${m.orders_saved}`], ["Still late", `${m.orders_still_late}`],
                    ["Penalty avoided", inr(m.penalty_avoided)], ["Net benefit", inr(m.net_benefit)], ["Arrival", dayOf(p.metrics.new_eta as string | undefined)]].map(([k, v]) => (
                    <div key={k} className={`rounded-lg bg-[#f6f6f7] p-2 ${k === "Net benefit" && top ? "ring-1 ring-[#16a34a]" : ""}`}>
                      <dt className="text-[10px] text-[#8a8a8f]">{k}</dt><dd className="font-semibold">{v}</dd></div>))}
                </dl>
              ) : (
                <div className="mt-3 rounded-lg bg-[#fdecee] p-3 text-xs text-[#9b1c2e]">
                  <div className="font-semibold">Not feasible</div>
                  <ul className="mt-1 list-disc pl-4">{p.reasons.map((r) => <li key={r}>{r}</li>)}</ul>
                </div>
              )}

              {p.feasible && p.steps.length > 0 && (
                <ol className="mt-3 space-y-1 text-[11px] text-[#55555a]">
                  {p.steps.map((s) => <li key={s.seq} className="flex gap-2"><span className={s.status === "done" ? "text-[#16a34a]" : "text-[#9a9aa0]"}>{s.status === "done" ? "✓" : `${s.seq}.`}</span><span>{s.description}</span></li>)}
                </ol>)}
              {p.ai_rationale && <p className="mt-3 rounded-lg bg-[#f9f5ff] p-2 text-[11px] text-[#55555a]"><b>AI note:</b> {p.ai_rationale}</p>}

              <div className="mt-auto pt-3">
                <p className="mb-2 text-[10px] text-[#8a8a8f]">Approved by {rolesLabel(p.approver_roles)}, confirmed by {rolesLabel(p.executor_roles)} · v{p.version}</p>
                <PlanControls plan={p} role={role} inFlight={inFlight} />
              </div>
            </section>
          );
        })}
      </div>
    </>
  );
}
