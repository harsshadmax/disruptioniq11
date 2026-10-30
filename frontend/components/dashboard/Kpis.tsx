import { AlertTriangle, ClipboardCheck, Gauge, Truck } from "lucide-react";
import type { Kpi } from "@/lib/types";

const ICONS = { truck: Truck, alert: AlertTriangle, clipboard: ClipboardCheck, gauge: Gauge };
const TONES = {
  green: "bg-[#e6f6ea] text-[#16a34a]",
  red: "bg-[#fdecee] text-[#e5384f]",
  orange: "bg-[#fff1e3] text-[#f08a24]",
  blue: "bg-[#e8f0fe] text-[#3b6fe0]",
};

export function Kpis({ items }: { items: Kpi[] }) {
  return (
    <div className="grid flex-1 grid-cols-2 gap-4 xl:grid-cols-4">
      {items.map((k) => {
        const Icon = ICONS[k.icon];
        return (
          <div key={k.label} className="rounded-2xl bg-white p-4 shadow-sm">
            <div className="flex items-center gap-3">
              <div className={`flex size-11 items-center justify-center rounded-xl ${TONES[k.tone]}`}>
                <Icon className="size-5" />
              </div>
              <div className="text-xs font-medium text-[#3a3a3f]">{k.label}</div>
            </div>
            <div className="mt-3 flex items-end justify-between gap-2">
              <div className="text-3xl font-bold tracking-tight text-[#1c1c1e]">{k.value}</div>
              <div className={`text-right text-[11px] font-medium ${k.good ? "text-[#16a34a]" : "text-[#e5384f]"}`}>{k.note}</div>
            </div>
          </div>
        );
      })}
    </div>
  );
}
