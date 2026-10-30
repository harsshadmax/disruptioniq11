import { AlertTriangle, ClipboardCheck, Gauge, MoreVertical, Truck } from "lucide-react";
import type { Kpi } from "@/lib/types";

const ICONS = { truck: Truck, alert: AlertTriangle, clipboard: ClipboardCheck, gauge: Gauge };
const EDGE = { green: "#2e7d4f", red: "#c8352b", orange: "#c77700", blue: "#1f4e8c" };

/** The template's "Operations overview": four figures, each with a coloured left rule and a small status pill. */
export function Kpis({ items, updatedAt }: { items: Kpi[]; updatedAt?: number }) {
  const time = updatedAt ? new Date(updatedAt).toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" }) : "";
  return (
    <section className="rounded-2xl border border-[#ddd9d0] bg-white p-4" aria-label="Operations overview">
      <div className="mb-4 flex items-center justify-between">
        <h2 className="text-[15px] font-bold text-[#1b2430]">Operations overview</h2>
        <div className="flex items-center gap-2 text-xs text-[#6b7480]" suppressHydrationWarning>
          {time && <span>Last updated: Today, {time}</span>}
          <MoreVertical className="size-4" aria-hidden />
        </div>
      </div>
      <div className="grid grid-cols-2 gap-x-6 gap-y-5 lg:grid-cols-4">
        {items.map((k) => {
          const Icon = ICONS[k.icon];
          return (
            <div key={k.label} className="border-l-2 pl-4" style={{ borderColor: EDGE[k.tone] }}>
              <div className="flex items-center gap-2 text-xs text-[#5c6670]"><Icon className="size-3.5" aria-hidden />{k.label}</div>
              <div className="mt-3 flex items-center justify-between gap-2">
                <div className="text-[28px] font-bold leading-none tracking-tight text-[#1b2430]">{k.value}</div>
                <span className={`rounded-md px-2 py-0.5 text-[10px] font-semibold ${k.good ? "bg-[#e3f0e7] text-[#2e7d4f]" : "bg-[#f8e4e1] text-[#c8352b]"}`}>{k.note}</span>
              </div>
            </div>
          );
        })}
      </div>
    </section>
  );
}
