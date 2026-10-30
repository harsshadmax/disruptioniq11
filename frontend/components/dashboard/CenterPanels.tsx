import { Check, Circle, Clock, MoreHorizontal } from "lucide-react";
import type { Disruption } from "@/lib/types";

/** The recovery steps without a card around them, so they can sit in a tab or in their own panel. */
export function RecoverySteps({ d }: { d: Disruption }) {
  return (
    <ol className="space-y-3">
      {d.timeline.map((s, i) => (
        <li key={s.title} className="relative flex gap-3">
          {i < d.timeline.length - 1 && <span className="absolute left-[9px] top-5 h-[calc(100%+4px)] w-px bg-[#e0dbef]" />}
          <span
            className={`relative z-10 mt-0.5 flex size-[18px] shrink-0 items-center justify-center rounded-full ${
              s.state === "done" ? "bg-[#16a34a] text-white" : s.state === "current" ? "bg-brand text-white" : "bg-[#e5e5e8] text-[#8a8a8f]"
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
  );
}

export function RecoveryTimeline({ d }: { d: Disruption }) {
  return (
    <div className="rounded-2xl border border-[#e6e8ec] bg-white p-4">
      <div className="mb-3 flex items-center justify-between">
        <div className="text-sm font-bold text-[#1c1c1e]">Recovery status</div>
        <MoreHorizontal className="size-4 text-[#8a8a8f]" />
      </div>
      <RecoverySteps d={d} />
    </div>
  );
}
