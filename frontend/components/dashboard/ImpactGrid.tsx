import { MoreVertical } from "lucide-react";
import type { Disruption } from "@/lib/types";
import { coverage } from "./coverage";

function Bars({ values }: { values: number[] }) {
  const max = Math.max(...values, 1);
  if (values.length === 0) return <div className="h-10" />;
  return (
    <div className="mt-3 flex h-10 items-end gap-1" aria-hidden>
      {values.slice(0, 8).map((v, i) => (
        <span key={i} className="flex-1 rounded-t-sm bg-gradient-to-b from-[#a99af0] to-[#efeafd]" style={{ height: `${Math.max(12, (v / max) * 100)}%` }} />
      ))}
    </div>
  );
}

/** The template's "Current loading status": four figures with a small bar sketch each, built from the ranked orders. */
export function ImpactGrid({ d }: { d: Disruption }) {
  const cov = coverage(d);
  const cells = [
    { value: String(d.affectedOrders).padStart(2, "0"), label: "Orders at risk", bars: d.orders.map((o) => o.score) },
    { value: cov.pct === null ? "n/a" : `${cov.pct}%`, label: "Recovery coverage", bars: d.planList.filter((p) => p.feasible).map((p) => p.metrics.orders_saved) },
    { value: String(d.unitsShort), label: "Units short", bars: d.orders.map((o) => o.uncovered_qty) },
    { value: d.penaltyExposed, label: "Penalty exposed", bars: d.orders.map((o) => o.sla_penalty) },
  ];
  return (
    <section className="flex flex-col rounded-2xl border border-[#e6e8ec] bg-white p-4" aria-label="Impact summary">
      <div className="mb-3 flex items-center justify-between">
        <h2 className="text-[15px] font-bold text-[#1c1c1e]">Impact summary</h2>
        <MoreVertical className="size-4 text-[#8a8a8f]" aria-hidden />
      </div>
      <div className="grid flex-1 grid-cols-2 overflow-hidden rounded-xl border border-[#e6e8ec]">
        {cells.map((c, i) => (
          <div key={c.label} className={`p-4 ${i % 2 === 0 ? "border-r border-[#e6e8ec]" : ""} ${i < 2 ? "border-b border-[#e6e8ec]" : ""}`}>
            <div className="text-2xl font-bold tracking-tight text-[#1c1c1e]">{c.value}</div>
            <div className="text-xs text-[#6b6b70]">{c.label}</div>
            <Bars values={c.bars} />
          </div>
        ))}
      </div>
      <p className="mt-2 text-[10px] text-[#9a9aa0]">Best ETA with the recommended plan: {d.bestEta}</p>
    </section>
  );
}
