"use client";

import { Loader2, RefreshCw, Sparkles } from "lucide-react";
import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { Disruption } from "@/lib/types";

/** The AI's (or the rules') words about the recommended plan, with the rewrite button as the one action. */
export function AiCard({
  d, text, source, canRefresh, busy, error, onRefresh,
}: {
  d: Disruption; text: string; source: "ai" | "rules" | "template"; canRefresh: boolean; busy: boolean;
  error: string | null; onRefresh: () => void;
}) {
  return (
    <section className="flex flex-col rounded-2xl border border-[#e6e8ec] bg-white p-4" aria-label="AI recommendation">
      <div className="mb-3 flex items-center justify-between">
        <h2 className="flex items-center gap-2 text-[15px] font-bold text-[#1c1c1e]">
          <span className="flex size-6 items-center justify-center rounded-lg bg-brand-soft text-brand"><Sparkles className="size-3.5" /></span>
          AI recommendation
        </h2>
        <span className="rounded-full bg-brand-soft px-2.5 py-1 text-[10px] font-semibold text-brand-ink">{source === "ai" ? "AI" : "Rules"}</span>
      </div>
      <div className="mb-3 grid grid-cols-2 gap-2 text-xs">
        <div className="rounded-lg bg-brand-wash p-3">
          <div className="text-[10px] text-[#8a8a8f]">Recommended</div>
          <div className="font-semibold text-[#1c1c1e]">{d.recommended}</div>
        </div>
        <div className="rounded-lg bg-brand-wash p-3">
          <div className="text-[10px] text-[#8a8a8f]">Net benefit</div>
          <div className="font-bold text-brand-ink">{d.net}</div>
        </div>
      </div>
      <div className="rounded-xl rounded-tl-sm bg-brand-wash p-3 text-[12px] leading-relaxed text-[#3a3a3f]">{text}</div>
      {error && <p className="mt-2 text-[10px] text-[#e5384f]">{error}</p>}
      <p className="mt-2 text-[10px] text-[#9a9aa0]">
        {source === "ai" ? "AI-written text." : "Rule-written text (no AI key set)."} Every number comes from rules.
      </p>
      <button
        onClick={onRefresh} disabled={!canRefresh || busy}
        title={canRefresh ? "Rewrite this summary with AI" : "Your role cannot use AI text"}
        className="mt-3 flex items-center justify-center gap-2 rounded-lg border border-brand-edge bg-white px-4 py-2 text-xs font-semibold text-brand-ink disabled:opacity-40"
      >
        {busy ? <Loader2 className="size-3.5 animate-spin" /> : <RefreshCw className="size-3.5" />} Rewrite with AI
      </button>
    </section>
  );
}

export function PlanChart({ d }: { d: Disruption }) {
  return (
    <section className="rounded-2xl border border-[#e6e8ec] bg-white p-4" aria-label="Plan comparison">
      <div className="mb-2 flex items-center justify-between">
        <h2 className="text-[15px] font-bold text-[#1c1c1e]">Plan comparison</h2>
        <span className="text-[10px] text-[#8a8a8f]">₹ thousand</span>
      </div>
      <div className="h-[170px]">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={d.plans} barGap={3} margin={{ left: -22, right: 4, top: 4 }}>
            <CartesianGrid vertical={false} stroke="#eef0f2" />
            <XAxis dataKey="name" tick={{ fontSize: 10, fill: "#8a8a8f" }} axisLine={false} tickLine={false} />
            <YAxis tick={{ fontSize: 10, fill: "#8a8a8f" }} axisLine={false} tickLine={false} />
            <Tooltip cursor={{ fill: "#f8f6ff" }} contentStyle={{ fontSize: 11, borderRadius: 8 }} />
            <Legend iconType="circle" iconSize={7} wrapperStyle={{ fontSize: 10 }} />
            <Bar dataKey="cost" name="Cost" fill="#d3c9f5" radius={[4, 4, 0, 0]} />
            <Bar dataKey="penaltyAvoided" name="Penalty avoided" fill="#7a63d6" radius={[4, 4, 0, 0]} />
          </BarChart>
        </ResponsiveContainer>
      </div>
    </section>
  );
}
