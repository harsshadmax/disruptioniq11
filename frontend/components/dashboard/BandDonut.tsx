import { MoreVertical } from "lucide-react";
import type { Disruption } from "@/lib/types";

/** The template's "Order status" donut: the at-risk orders split by risk band. */
export function BandDonut({ d }: { d: Disruption }) {
  const total = d.bands.high + d.bands.medium + d.bands.low;
  const newly = d.orders.filter((o) => o.newly_at_risk).length;
  const segs = [
    { label: "High risk", n: d.bands.high, color: "#e5384f" },
    { label: "Medium", n: d.bands.medium, color: "#f59e0b" },
    { label: "Low", n: d.bands.low, color: "#16a34a" },
  ];
  const r = 48;
  const c = 2 * Math.PI * r;
  const pct = (n: number) => (total ? Math.round((n / total) * 100) : 0);
  let acc = 0;
  return (
    <section className="flex flex-col rounded-2xl border border-[#e6e8ec] bg-white p-4" aria-label="Order risk bands">
      <div className="mb-2 flex items-center justify-between">
        <h2 className="text-[15px] font-bold text-[#1c1c1e]">Order risk bands</h2>
        <MoreVertical className="size-4 text-[#8a8a8f]" aria-hidden />
      </div>
      <div className="relative mx-auto my-2 size-40" role="img" aria-label={`${total} orders at risk: ${d.bands.high} high, ${d.bands.medium} medium, ${d.bands.low} low`}>
        <svg viewBox="0 0 120 120" className="size-full -rotate-90">
          <circle cx="60" cy="60" r={r} fill="none" stroke="#eef0f2" strokeWidth="12" />
          {segs.filter((s) => s.n > 0).map((s) => {
            const len = (s.n / total) * c;
            const el = (
              <circle
                key={s.label} cx="60" cy="60" r={r} fill="none" stroke={s.color} strokeWidth="12"
                strokeDasharray={`${Math.max(0, len - 2)} ${c - Math.max(0, len - 2)}`} strokeDashoffset={-acc}
              />
            );
            acc += len;
            return el;
          })}
        </svg>
        <div className="absolute inset-0 flex flex-col items-center justify-center">
          <span className="text-3xl font-bold text-[#1c1c1e]">{total.toLocaleString("en-IN")}</span>
          <span className="text-[11px] text-[#8a8a8f]">Orders at risk</span>
        </div>
      </div>
      <dl className="mt-auto grid grid-cols-2 gap-x-4 gap-y-2.5 text-xs">
        {[...segs, { label: "Newly at risk", n: newly, color: "#14b8a6" }].map((s) => (
          <div key={s.label}>
            <dt className="flex items-center gap-1.5 text-[#55555a]"><span className="size-2 rounded-full" style={{ background: s.color }} />{s.label}</dt>
            <dd className="pl-3.5 text-[11px] text-[#8a8a8f]">{pct(s.n)}% · {s.n}</dd>
          </div>
        ))}
      </dl>
    </section>
  );
}
