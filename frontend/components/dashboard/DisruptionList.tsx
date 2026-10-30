import { ClipboardCheck, MapPin, Package } from "lucide-react";
import type { Band, Disruption } from "@/lib/types";

const SEVERITY: Record<Band, string> = {
  high: "bg-[#fdecee] text-[#e5384f]",
  medium: "bg-[#fff1e3] text-[#d9741a]",
  low: "bg-[#e6f6ea] text-[#16a34a]",
  info: "bg-[#eef0f3] text-[#555]",
};

const TYPE_CHIP: Record<Disruption["type"], string> = {
  "Late shipment": "bg-[#e3ecff] text-[#3b6fe0]",
  "Supplier delay": "bg-[#f1e6ff] text-[#7a3fd1]",
  "Stock shortage": "bg-[#fff4c9] text-[#9a7400]",
};

export function DisruptionList({
  items, selectedId, onSelect,
}: { items: Disruption[]; selectedId: string; onSelect: (id: string) => void }) {
  return (
    <div className="flex flex-col gap-3">
      {items.map((d) => {
        const selected = d.id === selectedId;
        return (
          <button
            key={d.id}
            onClick={() => onSelect(d.id)}
            className={`rounded-2xl bg-white p-4 text-left shadow-sm transition ${
              selected ? "border-2 border-[#e5384f]" : "border-2 border-transparent hover:border-[#f2c9ce]"
            }`}
          >
            <div className="text-[15px] font-bold text-[#1c1c1e]">{d.ref}</div>
            <div className="text-xs text-[#6b6b70]">{d.title}</div>
            <div className="mt-2 flex flex-wrap gap-1.5">
              <span className={`rounded-md px-2 py-0.5 text-[10px] font-semibold ${TYPE_CHIP[d.type]}`}>{d.type}</span>
              <span className={`rounded-md px-2 py-0.5 text-[10px] font-semibold capitalize ${SEVERITY[d.severity]}`}>
                {d.severity} risk
              </span>
            </div>
            <div className="mt-3 flex items-start gap-2 text-xs">
              <MapPin className="mt-0.5 size-3.5 shrink-0 text-[#e5384f]" />
              <div>
                <div className="font-semibold text-[#1c1c1e]">{d.warehouse} warehouse</div>
                <div className="text-[11px] text-[#8a8a8f]">{d.etaChange}</div>
              </div>
            </div>
            <div className="mt-3 flex items-center justify-between border-t border-[#f0f0f2] pt-3">
              <div className="flex items-center gap-2">
                <span className="flex size-7 items-center justify-center rounded-full bg-[#eef0f3] text-[#555]">
                  <ClipboardCheck className="size-3.5" />
                </span>
                <div className="leading-tight">
                  <div className="text-[10px] text-[#8a8a8f]">Plan status</div>
                  <div className="text-xs font-semibold text-[#1c1c1e]">{d.planStatus}</div>
                </div>
              </div>
              <span className="flex items-center gap-1 rounded-full bg-[#fdecee] px-2 py-1 text-[11px] font-semibold text-[#e5384f]">
                <Package className="size-3.5" />
                {d.affectedOrders}
              </span>
            </div>
          </button>
        );
      })}
    </div>
  );
}
