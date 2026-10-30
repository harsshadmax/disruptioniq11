"use client";

import { useState } from "react";
import { ChevronDown } from "lucide-react";
import { Area, AreaChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis, type TooltipContentProps } from "recharts";
import type { Disruption } from "@/lib/types";

const SERIES = [
  { key: "score", label: "Risk score", color: "#1f4e8c" },
  { key: "uncovered", label: "Uncovered %", color: "#14b8a6" },
] as const;
type Key = (typeof SERIES)[number]["key"];
const LIMITS = [6, 10, 20];

type Row = { name: string; customer: string; score: number; uncovered: number };

function Tip({ active, payload }: TooltipContentProps) {
  if (!active || !payload?.length) return null;
  const row = payload[0].payload as Row;
  return (
    <div className="rounded-lg border border-[#ddd9d0] bg-white p-3 text-xs shadow-lg">
      <div className="font-semibold text-[#1b2430]">{row.name}</div>
      <div className="mb-1.5 text-[10px] text-[#6b7480]">{row.customer}</div>
      {SERIES.map((s) => (
        <div key={s.key} className="flex items-center justify-between gap-6">
          <span className="flex items-center gap-1.5 text-[#4a545e]"><span className="size-2 rounded-full" style={{ background: s.color }} />{s.label}</span>
          <b>{row[s.key]}{s.key === "uncovered" ? "%" : ""}</b>
        </div>
      ))}
    </div>
  );
}

/** The template's "Delivery performance" line chart, drawn from the ranked orders of the chosen disruption. */
export function RiskChart({ d }: { d: Disruption }) {
  const [limit, setLimit] = useState(LIMITS[0]);
  const [on, setOn] = useState<Record<Key, boolean>>({ score: true, uncovered: true });
  const data: Row[] = d.orders.slice(0, limit).map((o) => ({
    name: o.order_ref, customer: o.customer, score: Math.round(o.score * 10) / 10,
    uncovered: o.order_qty ? Math.round((o.uncovered_qty / o.order_qty) * 100) : 0,
  }));
  return (
    <section className="flex flex-col rounded-2xl border border-[#ddd9d0] bg-white p-4" aria-label="Order risk ranking">
      <div className="mb-3 flex items-center justify-between gap-2">
        <h2 className="text-[15px] font-bold text-[#1b2430]">Order risk ranking</h2>
        <label className="relative">
          <span className="sr-only">Orders shown</span>
          <select
            value={limit} onChange={(e) => setLimit(Number(e.target.value))}
            className="h-8 cursor-pointer appearance-none rounded-lg border border-[#ddd9d0] bg-white pl-3 pr-8 text-xs font-medium text-[#2f3944] outline-none focus:border-brand"
          >
            {LIMITS.map((n) => <option key={n} value={n}>Top {n}</option>)}
          </select>
          <ChevronDown className="pointer-events-none absolute right-2.5 top-1/2 size-3.5 -translate-y-1/2 text-[#6b7480]" />
        </label>
      </div>
      <div className="mb-3 grid grid-cols-2 overflow-hidden rounded-lg border border-[#ddd9d0] text-xs">
        {SERIES.map((s, i) => (
          <button
            key={s.key} type="button" aria-pressed={on[s.key]} onClick={() => setOn((m) => ({ ...m, [s.key]: !m[s.key] }))}
            className={`flex items-center justify-center gap-2 py-2 ${i === 0 ? "border-r border-[#ddd9d0]" : ""} ${on[s.key] ? "font-semibold text-[#1b2430]" : "text-[#7d8791]"}`}
          >
            <span className="size-2 rounded-full" style={{ background: on[s.key] ? s.color : "#cfcac0" }} />{s.label}
          </button>
        ))}
      </div>
      <div className="min-h-[240px] flex-1">
        {data.length === 0 ? (
          <div className="flex h-full items-center justify-center text-xs text-[#6b7480]">No orders at risk.</div>
        ) : (
          <ResponsiveContainer width="100%" height="100%" minHeight={240}>
            <AreaChart data={data} margin={{ left: -16, right: 8, top: 8, bottom: 0 }}>
              <defs>
                <linearGradient id="riskFill" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="#1f4e8c" stopOpacity={0.22} />
                  <stop offset="100%" stopColor="#1f4e8c" stopOpacity={0} />
                </linearGradient>
              </defs>
              <CartesianGrid stroke="#ece9e2" />
              <XAxis dataKey="name" tick={{ fontSize: 10, fill: "#6b7480" }} axisLine={false} tickLine={false} tickFormatter={(v: string) => v.replace("ORD-", "")} />
              <YAxis domain={[0, 100]} ticks={[0, 25, 50, 75, 100]} tick={{ fontSize: 10, fill: "#6b7480" }} axisLine={false} tickLine={false} />
              <Tooltip content={Tip} cursor={{ stroke: "#1f4e8c", strokeDasharray: "3 3" }} />
              {on.score && (
                <Area type="monotone" dataKey="score" stroke="#1f4e8c" strokeWidth={2} fill="url(#riskFill)"
                  dot={{ r: 3, fill: "#fff", stroke: "#1f4e8c", strokeWidth: 1.5 }} activeDot={{ r: 5 }} />
              )}
              {on.uncovered && (
                <Area type="monotone" dataKey="uncovered" stroke="#14b8a6" strokeWidth={2} fill="none"
                  dot={{ r: 3, fill: "#fff", stroke: "#14b8a6", strokeWidth: 1.5 }} activeDot={{ r: 5 }} />
              )}
            </AreaChart>
          </ResponsiveContainer>
        )}
      </div>
    </section>
  );
}
