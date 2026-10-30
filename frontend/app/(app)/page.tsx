"use client";

import Link from "next/link";
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CalendarDays, ChevronRight, Download, Loader2, Play } from "lucide-react";
import { toast } from "sonner";
import { aiSummary, loadDashboard, runDetection } from "@/lib/api";
import { allowed, CAN } from "@/lib/api/types";
import { useAuth } from "@/lib/auth";
import type { Disruption } from "@/lib/types";
import { useSearch } from "@/components/app/AppShell";
import { Kpis } from "@/components/dashboard/Kpis";
import { DisruptionList } from "@/components/dashboard/DisruptionList";
import { ImpactStrip, RecoveryTimeline, RippleCard } from "@/components/dashboard/CenterPanels";
import { PlanActions } from "@/components/dashboard/PlanActions";
import { AiCard, PlanChart, RiskBands } from "@/components/dashboard/RightPanels";

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
  const qc = useQueryClient();
  const { user } = useAuth();
  const { query } = useSearch();
  const role = user?.role ?? "";
  const dash = useQuery({ queryKey: ["dashboard"], queryFn: loadDashboard, refetchInterval: 15000 });
  const data = dash.data;
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [aiText, setAiText] = useState<Record<number, { text: string; source: "ai" | "template" }>>({});
  const today = new Date().toLocaleDateString("en-GB", { weekday: "short", day: "numeric", month: "long", year: "numeric" });

  const detect = useMutation({
    mutationFn: runDetection,
    onSuccess: (r) => {
      toast.success(`Detection finished: ${r.created.length} new, ${r.updated.length} updated, ${r.resolved.length} resolved.`);
      qc.invalidateQueries();
    },
    onError: (e) => toast.error(e instanceof Error ? e.message : "Detection failed"),
  });
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
      <section className="flex flex-col gap-4 xl:flex-row xl:items-center">
        <div className="shrink-0 xl:w-[210px]">
          <h1 className="text-[26px] font-extrabold leading-tight tracking-tight text-[#1c1c1e]">Disruption Summary</h1>
          <span className="mt-2 inline-block rounded-full bg-[#1c1c1e] px-3 py-1 text-[11px] text-white" suppressHydrationWarning>{today}</span>
        </div>
        {data ? <Kpis items={data.kpis} /> : <div className="h-[104px] flex-1 animate-pulse rounded-2xl bg-white" />}
      </section>

      <section className="flex flex-wrap items-center gap-3 rounded-2xl bg-white px-4 py-3 shadow-sm">
        <CalendarDays className="size-4 text-[#8a8a8f]" />
        <div className="mr-auto leading-tight">
          <div className="text-sm font-semibold text-[#1c1c1e]">Disruption database</div>
          <div className="text-[11px] text-[#8a8a8f]">Synthetic demo data, refreshed every 15 seconds</div>
        </div>
        <Link href="/approvals" className="flex items-center gap-2 rounded-full bg-[#fde9d6] px-4 py-2 text-xs font-medium text-[#d9741a]">
          Pending approvals ({data?.pendingApprovals ?? 0}) <ChevronRight className="size-3.5" />
        </Link>
        <button onClick={() => d && downloadReport(d)} disabled={!d}
          className="flex items-center gap-2 rounded-full border border-[#d9d9de] bg-white px-4 py-2 text-xs font-medium text-[#1c1c1e] disabled:opacity-40">
          <Download className="size-3.5" /> Download report
        </button>
        {allowed(CAN.runDetection, role) && (
          <button onClick={() => detect.mutate()} disabled={detect.isPending} title="Scan stock, orders and shipments for new disruptions"
            className="flex items-center gap-2 rounded-full bg-[#e5384f] px-4 py-2 text-xs font-semibold text-white shadow-md shadow-[#e5384f]/25 disabled:opacity-50">
            {detect.isPending ? <Loader2 className="size-3.5 animate-spin" /> : <Play className="size-3.5" />} Run detection
          </button>
        )}
      </section>

      {dash.isLoading && <div className="h-80 animate-pulse rounded-2xl bg-white" />}
      {dash.error && !data && (
        <div role="alert" className="rounded-2xl bg-white p-6 text-sm shadow-sm">
          <div className="font-semibold text-[#9b1c2e]">Could not load disruptions</div>
          <div className="mt-1 text-[#6b6b70]">{(dash.error as Error).message}</div>
          <button onClick={() => dash.refetch()} className="mt-3 rounded-full bg-[#e5384f] px-4 py-2 text-xs font-semibold text-white">Retry</button>
        </div>
      )}
      {data && !d && (
        <div className="rounded-2xl bg-white p-8 text-center text-sm text-[#6b6b70] shadow-sm">
          {q ? "No disruption matches that search." : "No active disruptions. Stock and shipments look healthy."}
        </div>
      )}

      {d && (
        <section className="grid gap-4 lg:grid-cols-[250px_minmax(0,1fr)_290px]">
          <DisruptionList items={items} selectedId={d.id} onSelect={setSelectedId} />
          <div className="flex min-w-0 flex-col gap-4">
            <RippleCard d={d} />
            <ImpactStrip d={d} />
            <PlanActions d={d} role={role} />
            <RecoveryTimeline d={d} />
          </div>
          <div className="flex flex-col gap-4">
            <AiCard
              d={d} text={override?.text ?? d.aiSummary} source={override?.source ?? d.aiSource}
              canRefresh={allowed(CAN.useAi, role)} busy={ai.isPending && ai.variables === d.dbId}
              error={ai.isError && ai.variables === d.dbId ? (ai.error as Error).message : null}
              onRefresh={() => ai.mutate(d.dbId)}
            />
            <RiskBands d={d} />
            <PlanChart d={d} />
            <Link href={`/disruptions/${d.dbId}`} className="rounded-2xl bg-white p-4 text-center text-xs font-semibold text-[#e5384f] shadow-sm">
              Open full disruption page
            </Link>
          </div>
        </section>
      )}
    </>
  );
}
