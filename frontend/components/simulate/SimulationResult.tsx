"use client";

import { useState } from "react";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { SimulationResult as Result } from "@/lib/api/types";
import { BAND_TONE, Empty, inr, Panel, Pill } from "@/components/ui/bits";

const BASE = "#b9c9de";
const SIM = "#1f4e8c";

const METRICS = [
  { key: "orders", label: "Orders at risk", base: "baseline_orders", sim: "simulated_orders", fmt: (n: number) => String(n) },
  { key: "units", label: "Units short", base: "baseline_units_short", sim: "simulated_units_short", fmt: (n: number) => n.toLocaleString("en-IN") },
  { key: "penalty", label: "SLA penalty", base: "baseline_penalty", sim: "simulated_penalty", fmt: inr },
] as const;

/** Worse is always "more": more orders, more units short, more money at stake. */
function Compare({ label, base, sim, fmt, hint }: { label: string; base: number; sim: number; fmt: (n: number) => string; hint?: string }) {
  const diff = sim - base;
  const tone = diff > 0 ? "bg-[#f8e4e1] text-[#c8352b]" : diff < 0 ? "bg-[#e3f0e7] text-[#2e7d4f]" : "bg-[#ece9e2] text-[#555]";
  return (
    <div className="rounded-xl border border-[#ddd9d0] bg-white p-3" title={hint}>
      <div className="text-[11px] font-medium text-[#5c6670]">{label}</div>
      <div className="mt-1 text-2xl font-extrabold leading-none text-[#1b2430]">{fmt(sim)}</div>
      <div className="mt-2 flex flex-wrap items-center justify-between gap-x-2 gap-y-1 text-[11px] text-[#6b7480]">
        <span className="whitespace-nowrap">Now {fmt(base)}</span>
        <span className={`whitespace-nowrap rounded-md px-2 py-0.5 text-[10px] font-semibold ${tone}`}>
          {diff === 0 ? "No change" : `${diff > 0 ? "+" : "-"}${fmt(Math.abs(diff))}`}
        </span>
      </div>
    </div>
  );
}

export function SimulationResult({ result, stale }: { result: Result; stale: boolean }) {
  const [metric, setMetric] = useState<(typeof METRICS)[number]["key"]>("orders");
  const m = METRICS.find((x) => x.key === metric) ?? METRICS[0];
  const { baseline: b, simulated: s } = result;
  const data = result.by_warehouse.map((w) => ({ name: w.warehouse, Now: w[m.base], Simulated: w[m.sim] }));
  const quiet = s.orders_at_risk === 0 && b.orders_at_risk === 0;

  return (
    <div className="flex flex-col gap-4" aria-live="polite">
      <div className="flex flex-wrap items-center gap-2 rounded-xl border border-brand-edge bg-brand-wash px-4 py-2.5 text-xs text-brand-ink">
        <b>Simulated result.</b> <span>{result.note}</span>
        {stale && <span className="rounded-md bg-[#f8ecd3] px-2 py-0.5 text-[10px] font-semibold text-[#c77700]">Scenario edited since this run. Run again to update.</span>}
      </div>

      <ul className="list-disc space-y-0.5 pl-5 text-xs text-[#2f3944]">
        {result.events.map((e, i) => <li key={i}>{e}</li>)}
      </ul>

      <div className="grid grid-cols-2 gap-3 md:grid-cols-3">
        <Compare label="Orders at risk" base={b.orders_at_risk} sim={s.orders_at_risk} fmt={String} hint="Orders with at least one line that cannot be covered in time" />
        <Compare label="High-risk orders" base={b.high_risk_orders} sim={s.high_risk_orders} fmt={String} hint="Risk score of 60 or more" />
        <Compare label="Units short" base={b.units_short} sim={s.units_short} fmt={(n) => n.toLocaleString("en-IN")} />
        <Compare label="SLA penalty exposed" base={b.penalty_exposure} sim={s.penalty_exposure} fmt={inr} hint="Estimate: the penalty written on each at-risk order, counted once" />
        <Compare label="Order value at risk" base={b.value_at_risk} sim={s.value_at_risk} fmt={inr} hint="Estimate: the value of each at-risk order, counted once" />
        <Compare label="Customers affected" base={b.customers_affected} sim={s.customers_affected} fmt={String} hint={`${s.gold_customers_affected} gold`} />
      </div>
      <p className="-mt-2 text-[11px] text-[#6b7480]">
        {s.gold_customers_affected} gold customer{s.gold_customers_affected === 1 ? "" : "s"} affected. Money figures are estimates from the order data,
        not confirmed financial records. {result.newly_at_risk_orders} order{result.newly_at_risk_orders === 1 ? " is" : "s are"} at risk only because of this scenario.
      </p>

      <Panel
        title="By warehouse"
        aside={
          <div className="flex gap-1" role="group" aria-label="Chart measure">
            {METRICS.map((x) => (
              <button
                key={x.key} type="button" aria-pressed={metric === x.key} onClick={() => setMetric(x.key)}
                className={`rounded-md px-3 py-1 text-[11px] font-semibold ${metric === x.key ? "bg-brand text-white" : "border border-[#ddd9d0] text-[#4a545e]"}`}
              >{x.label}</button>
            ))}
          </div>
        }
      >
        <div className="h-64" role="img" aria-label={`${m.label} by warehouse, now compared with the simulation`}>
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: -8 }}>
              <CartesianGrid stroke="#ece9e2" vertical={false} />
              <XAxis dataKey="name" tick={{ fontSize: 11, fill: "#5c6670" }} axisLine={false} tickLine={false} />
              <YAxis tick={{ fontSize: 11, fill: "#5c6670" }} axisLine={false} tickLine={false} allowDecimals={false} />
              <Tooltip cursor={{ fill: "#f3f1ec" }} formatter={(v) => m.fmt(Number(v))} contentStyle={{ borderRadius: 8, fontSize: 12, border: "1px solid #ddd9d0" }} />
              <Bar dataKey="Now" fill={BASE} radius={[4, 4, 0, 0]} maxBarSize={36} />
              <Bar dataKey="Simulated" fill={SIM} radius={[4, 4, 0, 0]} maxBarSize={36} />
            </BarChart>
          </ResponsiveContainer>
        </div>
        <div className="mt-2 flex gap-4 text-[11px] text-[#4a545e]">
          <span className="flex items-center gap-1.5"><span className="size-2.5 rounded-sm" style={{ background: BASE }} />Now (real data)</span>
          <span className="flex items-center gap-1.5"><span className="size-2.5 rounded-sm" style={{ background: SIM }} />Simulated</span>
        </div>
      </Panel>

      <Panel title="Most affected orders" aside={`Top ${result.orders.length}, worst first`}>
        {result.orders.length === 0 ? (
          <Empty>{quiet ? "No order is at risk now, and this scenario does not put any at risk." : "This scenario puts no order at risk."}</Empty>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs">
              <thead className="text-[10px] uppercase tracking-wide text-[#6b7480]">
                <tr>{["Order", "Customer", "Due", "Short", "Penalty", "Warehouse", "Risk", "Was"].map((h) => <th key={h} className="px-3 py-2 font-medium">{h}</th>)}</tr>
              </thead>
              <tbody>
                {result.orders.map((o) => (
                  <tr key={o.order_ref} className="border-t border-[#ebe8e1]">
                    <td className="px-3 py-2 font-semibold">{o.order_ref}</td>
                    <td className="px-3 py-2">{o.customer} <span className="text-[10px] capitalize text-[#6b7480]">{o.tier}</span></td>
                    <td className="px-3 py-2">{new Date(o.due_date).toLocaleDateString("en-GB", { day: "numeric", month: "short" })}</td>
                    <td className="px-3 py-2">{o.uncovered_qty} of {o.order_qty}</td>
                    <td className="px-3 py-2">{inr(o.sla_penalty)}</td>
                    <td className="px-3 py-2">{o.warehouses.join(", ")}</td>
                    <td className="px-3 py-2"><Pill tone={BAND_TONE[o.band]}>{o.band} {Math.round(o.score)}</Pill></td>
                    <td className="px-3 py-2">{o.baseline_band ? <Pill tone={BAND_TONE[o.baseline_band]}>{o.baseline_band}</Pill> : <Pill tone="bg-[#e3f0e7] text-[#2e7d4f]">safe</Pill>}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Panel>
    </div>
  );
}
