import { MoreVertical, Truck } from "lucide-react";
import type { Band, Disruption } from "@/lib/types";

const SEVERITY: Record<Band, string> = {
  high: "bg-[#f8e4e1] text-[#c8352b]",
  medium: "bg-[#f8ecd3] text-[#c77700]",
  low: "bg-[#e3f0e7] text-[#2e7d4f]",
  info: "bg-[#ece9e2] text-[#555]",
};

/** How far along recovery is, from the plans' real statuses: nothing proposed, proposed, approved, done. */
function progress(d: Disruption): number {
  const s = d.planList.map((p) => p.status);
  if (s.includes("COMPLETED")) return 1;
  if (s.includes("EXECUTING") || s.includes("APPROVED")) return 0.7;
  if (s.includes("PROPOSED")) return 0.4;
  return 0.1;
}

/** The template's "Active fleet" list: one card per disruption, supplier to warehouse with a progress line. */
export function ActiveList({
  items, selectedId, onSelect,
}: { items: Disruption[]; selectedId: string; onSelect: (id: string) => void }) {
  return (
    <section className="flex flex-col rounded-2xl border border-[#ddd9d0] bg-white p-4" aria-label="Active disruptions">
      <div className="mb-3 flex items-center justify-between">
        <h2 className="text-[15px] font-bold text-[#1b2430]">Active disruptions</h2>
        <MoreVertical className="size-4 text-[#6b7480]" aria-hidden />
      </div>
      <ul className="flex max-h-[330px] flex-col gap-2.5 overflow-y-auto pr-0.5">
        {items.map((d) => {
          const selected = d.id === selectedId;
          const pct = Math.round(progress(d) * 100);
          return (
            <li key={d.id}>
              <button
                type="button" onClick={() => onSelect(d.id)} aria-pressed={selected}
                className={`w-full rounded-xl border p-3 text-left transition ${selected ? "border-brand bg-brand-wash" : "border-[#ddd9d0] bg-white hover:border-brand-edge"}`}
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="text-xs"><b className="text-[#1b2430]">{d.ref}</b> <span className="text-[#6b7480]">• {d.etaChange}</span></span>
                  <span className={`shrink-0 rounded-md px-2.5 py-0.5 text-[10px] font-semibold capitalize ${SEVERITY[d.severity]}`}>{d.severity} risk</span>
                </div>
                <div className="mt-3 flex items-center gap-3">
                  <span className="flex size-10 shrink-0 items-center justify-center rounded-lg bg-[#f1efe9] text-[#4a545e]"><Truck className="size-5" /></span>
                  <div className="min-w-0 flex-1">
                    <div className="flex justify-between gap-2 text-xs font-bold text-[#1b2430]">
                      <span className="truncate">{d.supplier}</span>
                      <span className="truncate text-right">{d.warehouse}</span>
                    </div>
                    <div className="relative my-2 h-1.5 rounded-full bg-[#ddd9d0]" role="progressbar" aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100} aria-label={`Recovery progress: ${d.planStatus}`}>
                      <div className="h-full rounded-full bg-[#1b2430]" style={{ width: `${pct}%` }} />
                      <span className="absolute top-1/2 size-3.5 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-white bg-[#1b2430]" style={{ left: `${pct}%` }} />
                    </div>
                    <div className="flex justify-between text-[10px] text-[#6b7480]"><span>Supplier</span><span>Plan: {d.planStatus}</span></div>
                  </div>
                </div>
              </button>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
