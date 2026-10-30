"use client";

import Link from "next/link";
import { useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { ChevronDown, ChevronRight, Download } from "lucide-react";
import { aiSummary, loadDashboard } from "@/lib/api";
import { allowed, CAN } from "@/lib/api/types";
import { useAuth } from "@/lib/auth";
import type { Disruption } from "@/lib/types";
import { useSearch } from "@/components/app/AppShell";
import { Kpis } from "@/components/dashboard/Kpis";
import { RiskChart } from "@/components/dashboard/RiskChart";
import { MapPanel } from "@/components/dashboard/MapPanel";
import { ActiveList } from "@/components/dashboard/ActiveList";
import { ImpactGrid } from "@/components/dashboard/ImpactGrid";
import { BandDonut } from "@/components/dashboard/BandDonut";
import { RecoveryTimeline } from "@/components/dashboard/CenterPanels";
import { PlanActions } from "@/components/dashboard/PlanActions";
import { AiCard, PlanChart } from "@/components/dashboard/RightPanels";

function downloadReport(d: Disruption) {
  const head = ["rank", "order_ref", "customer", "tier", "due_date", "risk_score", "band", "uncovered_qty", "order_qty", "sla_penalty"];
  const rows = d.orders.map((o) => [o.rank, o.order_ref, o.customer, o.tier, o.due_date, o.score, o.band, o.uncovered_qty, o.order_qty, o.sla_penalty]);
  const csv = [head, ...rows].map((r) => r.map((c) => `"${String(c).replace(/"/g, '""')}"`).join(",")).join("\n");
  const url = URL.createObjectURL(new Blob([csv], { type: "text/csv" }));
  const a = document.createElement("a");
  a.href = url;
  a.download = `${d.ref}-orders-at-risk.csv`;
  a.click();
  URL.revokeObjectURL(url);
}

export default function DashboardPage() {
  const { user } = useAuth();
  const { query } = useSearch();
  const role = user?.role ?? "";
  const dash = useQuery({ queryKey: ["dashboard"], queryFn: loadDashboard, refetchInterval: 15000 });
  const data = dash.data;
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [aiText, setAiText] = useState<Record<number, { text: string; source: "ai" | "template" }>>({});

  const ai = useMutation({
    mutationFn: aiSummary,
    onSuccess: (r, id) => setAiText((m) => ({ ...m, [id]: { text: r.text, source: r.source === "ai" ? "ai" : "template" } })),
  });

  const q = query.trim().toLowerCase();
  const items = (data?.items ?? []).filter((d) => !q || d.searchText.includes(q));
  const d = items.find((x) => x.id === selectedId) ?? items[0];
  const override = d ? aiText[d.dbId] : undefined;

  return (
    <>
      {data ? <Kpis items={data.kpis} updatedAt={dash.dataUpdatedAt} /> : <div className="h-[132px] animate-pulse rounded-2xl bg-white" />}

      {dash.isLoading && <div className="h-80 animate-pulse rounded-2xl bg-white" />}
      {dash.error && !data && (
        <div role="alert" className="rounded-2xl border border-[#ddd9d0] bg-white p-6 text-sm">
          <div className="font-semibold text-[#8c2a22]">Could not load disruptions</div>
          <div className="mt-1 text-[#5c6670]">{(dash.error as Error).message}</div>
          <button onClick={() => dash.refetch()} className="mt-3 rounded-lg bg-brand px-4 py-2 text-xs font-semibold text-white">Retry</button>
        </div>
      )}
      {data && !d && (
        <div className="rounded-2xl border border-[#ddd9d0] bg-white p-8 text-center text-sm text-[#5c6670]">
          {q ? "No disruption matches that search." : "No active disruptions. Stock and shipments look healthy."}
        </div>
      )}

      {d && (
        <>
          <section className="flex flex-wrap items-center gap-2">
            <label className="relative">
              <span className="sr-only">Select disruption</span>
              <select
                value={d.id} onChange={(e) => setSelectedId(e.target.value)}
                className="h-9 cursor-pointer appearance-none rounded-lg border border-[#ddd9d0] bg-white pl-3 pr-9 text-xs font-semibold text-[#1b2430] outline-none focus:border-brand"
              >
                {items.map((x) => <option key={x.id} value={x.id}>{x.ref} · {x.warehouse} · {x.type}</option>)}
              </select>
              <ChevronDown className="pointer-events-none absolute right-3 top-1/2 size-3.5 -translate-y-1/2 text-[#6b7480]" />
            </label>
            <div className="ml-auto flex flex-wrap items-center gap-2">
              <Link href="/approvals" className="flex h-9 items-center gap-2 rounded-lg bg-[#f8e3cc] px-3 text-xs font-medium text-[#c77700]">
                Pending approvals ({data?.pendingApprovals ?? 0}) <ChevronRight className="size-3.5" />
              </Link>
              <button onClick={() => downloadReport(d)}
                className="flex h-9 items-center gap-2 rounded-lg border border-[#ddd9d0] bg-white px-3 text-xs font-medium text-[#2f3944]">
                <Download className="size-3.5" /> Download report
              </button>
            </div>
          </section>

          <section className="grid gap-4 xl:grid-cols-[minmax(0,5fr)_minmax(0,6fr)]">
            <RiskChart d={d} />
            <MapPanel d={d} />
          </section>

          <section className="grid gap-4 xl:grid-cols-[minmax(0,1.1fr)_minmax(0,1fr)_minmax(0,0.9fr)]">
            <ActiveList items={items} selectedId={d.id} onSelect={setSelectedId} />
            <ImpactGrid d={d} />
            <BandDonut d={d} />
          </section>

          <section className="grid gap-4 xl:grid-cols-[minmax(0,1.5fr)_minmax(0,1fr)]">
            <div className="flex min-w-0 flex-col gap-4">
              <PlanActions d={d} role={role} />
              <RecoveryTimeline d={d} />
            </div>
            <div className="flex min-w-0 flex-col gap-4">
              <AiCard
                d={d} text={override?.text ?? d.aiSummary} source={override?.source ?? d.aiSource}
                canRefresh={allowed(CAN.useAi, role)} busy={ai.isPending && ai.variables === d.dbId}
                error={ai.isError && ai.variables === d.dbId ? (ai.error as Error).message : null}
                onRefresh={() => ai.mutate(d.dbId)}
              />
              <PlanChart d={d} />
              <Link href={`/disruptions/${d.dbId}`} className="rounded-2xl border border-[#ddd9d0] bg-white p-3 text-center text-xs font-semibold text-brand">
                Open full disruption page
              </Link>
            </div>
          </section>
        </>
      )}
    </>
  );
}
