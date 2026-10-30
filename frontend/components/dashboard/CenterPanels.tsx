import { Check, Circle, Clock, MoreHorizontal } from "lucide-react";
import type { Disruption } from "@/lib/types";
import { RippleMap } from "./RippleMap";

export function RippleCard({ d }: { d: Disruption }) {
  return (
    <div className="rounded-2xl bg-white p-3 shadow-sm">
      <div className="mb-2 flex items-center justify-between px-1">
        <div>
          <div className="text-sm font-bold text-[#1c1c1e]">Ripple map</div>
          <div className="text-[11px] text-[#8a8a8f]">{d.supplier} → {d.warehouse} → affected orders</div>
        </div>
        <div className="flex items-center gap-3 text-[10px] text-[#6b6b70]">
          <Legend color="#e5384f" label="High" />
          <Legend color="#f59e0b" label="Medium" />
          <Legend color="#16a34a" label="Low" />
        </div>
      </div>
      <RippleMap data={d.ripple} />
    </div>
  );
}

function Legend({ color, label }: { color: string; label: string }) {
  return (
    <span className="flex items-center gap-1">
      <span className="size-2 rounded-full" style={{ background: color }} />
      {label}
    </span>
  );
}

export function ImpactStrip({ d }: { d: Disruption }) {
  const items = [
    { label: "Affected orders", value: String(d.affectedOrders) },
    { label: "Units short", value: String(d.unitsShort) },
    { label: "Penalty exposed", value: d.penaltyExposed },
    { label: "Best ETA", value: d.bestEta },
  ];
  return (
    <div className="grid grid-cols-4 gap-2 rounded-2xl bg-white p-3 shadow-sm">
      {items.map((i) => (
        <div key={i.label} className="rounded-xl bg-[#f7f7f8] px-3 py-2">
          <div className="text-[10px] text-[#8a8a8f]">{i.label}</div>
          <div className="text-lg font-bold text-[#1c1c1e]">{i.value}</div>
        </div>
      ))}
    </div>
  );
}

export function RecoveryTimeline({ d }: { d: Disruption }) {
  return (
    <div className="rounded-2xl bg-white p-4 shadow-sm">
      <div className="mb-3 flex items-center justify-between">
        <div className="text-sm font-bold text-[#1c1c1e]">Recovery status</div>
        <MoreHorizontal className="size-4 text-[#8a8a8f]" />
      </div>
      <ol className="space-y-3">
        {d.timeline.map((s, i) => (
          <li key={s.title} className="relative flex gap-3">
            {i < d.timeline.length - 1 && <span className="absolute left-[9px] top-5 h-[calc(100%+4px)] w-px bg-[#e5e5e8]" />}
            <span
              className={`relative z-10 mt-0.5 flex size-[18px] shrink-0 items-center justify-center rounded-full ${
                s.state === "done" ? "bg-[#16a34a] text-white" : s.state === "current" ? "bg-[#e5384f] text-white" : "bg-[#e5e5e8] text-[#8a8a8f]"
              }`}
            >
              {s.state === "done" ? <Check className="size-3" /> : s.state === "current" ? <Clock className="size-3" /> : <Circle className="size-2" />}
            </span>
            <div className="flex-1">
              <div className="flex items-start justify-between gap-3">
                <div className="text-xs font-semibold text-[#1c1c1e]">{s.title}</div>
                <div className="shrink-0 text-[10px] text-[#8a8a8f]">{s.when}</div>
              </div>
              <div className="text-[11px] text-[#6b6b70]">{s.detail}</div>
            </div>
          </li>
        ))}
      </ol>
    </div>
  );
}
