"use client";

import { Loader2, MoreHorizontal, RefreshCw, Sparkles } from "lucide-react";
import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { Disruption } from "@/lib/types";

export function AiCard({
  d, text, source, canRefresh, busy, error, onRefresh,
}: {
  d: Disruption; text: string; source: "ai" | "rules" | "template"; canRefresh: boolean; busy: boolean;
  error: string | null; onRefresh: () => void;
}) {
  return (
    <div className="rounded-2xl bg-white p-4 shadow-sm">
      <div className="mb-3 flex items-center justify-between">
        <div className="flex items-center gap-2 text-sm font-bold text-[#1c1c1e]">
          <span className="flex size-5 items-center justify-center rounded-full bg-[#fdecee] text-[#e5384f]">
            <Sparkles className="size-3" />
          </span>
          AI recommendation
        </div>
        <button
          onClick={onRefresh} disabled={!canRefresh || busy}
          title={canRefresh ? "Rewrite this summary with AI" : "Your role cannot use AI text"}
          className="flex size-6 items-center justify-center rounded-full bg-[#fdecee] text-[#e5384f] disabled:opacity-40"
        >
          {busy ? <Loader2 className="size-3.5 animate-spin" /> : <RefreshCw className="size-3.5" />}
        </button>
      </div>
      <div className="grid grid-cols-[1fr_1.15fr] gap-3">
        <dl className="space-y-3 text-xs">
          {[["Cost", d.metrics.cost], ["Orders saved", d.metrics.saved], ["Penalty avoided", d.metrics.penalty]].map(([k, v]) => (
            <div key={k}>
              <dt className="text-[10px] text-[#8a8a8f]">{k}</dt>
              <dd className="text-lg font-bold leading-tight text-[#1c1c1e]">{v}</dd>
            </div>
          ))}
        </dl>
        <div className="flex flex-col justify-between rounded-2xl bg-gradient-to-br from-[#2a2a2e] via-[#3a1a20] to-[#e5384f] p-3 text-white">
          <div className="text-[10px] uppercase tracking-wide opacity-70">Net benefit</div>
          <div className="whitespace-nowrap text-xl font-bold leading-tight">{d.net}</div>
          <div className="text-[11px] font-medium opacity-90">{d.recommended}</div>
        </div>
      </div>
      <p className="mt-3 text-[11px] leading-relaxed text-[#55555a]">{text}</p>
      {error && <p className="mt-2 text-[10px] text-[#e5384f]">{error}</p>}
      <p className="mt-2 text-[10px] text-[#9a9aa0]">
        {source === "ai" ? "AI-written text." : "Rule-written text (no AI key set)."} Every number comes from rules.
      </p>
    </div>
  );
}

export function RiskBands({ d }: { d: Disruption }) {
  const total = Math.max(1, d.bands.high + d.bands.medium + d.bands.low);
  const pct = (n: number) => Math.round((n / total) * 1000) / 10;
  const segs = [
    { label: "High risk", n: d.bands.high, color: "#1c1c1e", text: "#fff" },
    { label: "Medium", n: d.bands.medium, color: "#f9c9d0", text: "#c42a40" },
    { label: "Low", n: d.bands.low, color: "#e5e5e8", text: "#555" },
  ];
  return (
    <div className="rounded-2xl bg-white p-4 shadow-sm">
      <div className="mb-3 flex items-center justify-between">
        <div className="text-sm font-bold text-[#1c1c1e]">Order risk bands</div>
        <MoreHorizontal className="size-4 text-[#8a8a8f]" />
      </div>
      <div className="flex h-9 overflow-hidden rounded-lg">
        {segs.filter((s) => s.n > 0).map((s) => (
          <div key={s.label} className="flex items-center justify-center text-[11px] font-semibold" style={{ width: `${pct(s.n)}%`, background: s.color, color: s.text }}>
            {pct(s.n)}%
          </div>
        ))}
      </div>
      <div className="mt-2 flex justify-between text-[10px] text-[#8a8a8f]">
        {segs.map((s) => <span key={s.label}>{s.label}: {s.n}</span>)}
      </div>
    </div>
  );
}

export function PlanChart({ d }: { d: Disruption }) {
  return (
    <div className="rounded-2xl bg-white p-4 shadow-sm">
      <div className="mb-2 flex items-center justify-between">
        <div className="text-sm font-bold text-[#1c1c1e]">Plan comparison</div>
        <span className="text-[10px] text-[#8a8a8f]">₹ thousand</span>
      </div>
      <div className="h-[150px]">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={d.plans} barGap={3} margin={{ left: -22, right: 4, top: 4 }}>
            <CartesianGrid vertical={false} stroke="#efeff1" />
            <XAxis dataKey="name" tick={{ fontSize: 10, fill: "#8a8a8f" }} axisLine={false} tickLine={false} />
            <YAxis tick={{ fontSize: 10, fill: "#8a8a8f" }} axisLine={false} tickLine={false} />
            <Tooltip cursor={{ fill: "#f7f7f8" }} contentStyle={{ fontSize: 11, borderRadius: 8 }} />
            <Legend iconType="circle" iconSize={7} wrapperStyle={{ fontSize: 10 }} />
            <Bar dataKey="cost" name="Cost" fill="#f9c9d0" radius={[4, 4, 0, 0]} />
            <Bar dataKey="penaltyAvoided" name="Penalty avoided" fill="#e5384f" radius={[4, 4, 0, 0]} />
          </BarChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
