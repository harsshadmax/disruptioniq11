"use client";

import { useState } from "react";
import type { Disruption } from "@/lib/types";
import { MapView } from "./MapView";
import { RippleMap } from "./RippleMap";

const VIEWS = [
  { key: "map", label: "Map" },
  { key: "ripple", label: "Ripple" },
] as const;

/** The template's map card: a street map of the route as the hero (the ripple graph is one tab over), legend strip along the bottom. */
export function MapPanel({ d }: { d: Disruption }) {
  const [view, setView] = useState<(typeof VIEWS)[number]["key"]>("map");
  const newly = d.orders.filter((o) => o.newly_at_risk).length;
  const cells = [
    { label: "High risk", n: d.bands.high, color: "#e5384f" },
    { label: "Medium", n: d.bands.medium, color: "#f59e0b" },
    { label: "Low", n: d.bands.low, color: "#16a34a" },
    { label: "Newly at risk", n: newly, color: "#14b8a6" },
  ];
  return (
    <section className="flex flex-col rounded-2xl border border-[#e6e8ec] bg-white p-4" aria-label="Disruption map">
      <div className="mb-3 flex items-start justify-between gap-3">
        <div>
          <h2 className="text-[15px] font-bold text-[#1c1c1e]">{view === "map" ? "Shipment route" : "Ripple map"}</h2>
          <p className="text-[11px] text-[#8a8a8f]">{d.supplier} → {d.warehouse} → affected orders</p>
        </div>
        <div className="flex overflow-hidden rounded-lg border border-[#e6e8ec] text-xs" role="tablist" aria-label="Map view">
          {VIEWS.map((v, i) => (
            <button
              key={v.key} type="button" role="tab" aria-selected={view === v.key} onClick={() => setView(v.key)}
              className={`px-3 py-1.5 font-medium ${i > 0 ? "border-l border-[#e6e8ec]" : ""} ${view === v.key ? "bg-brand-soft text-brand-ink" : "text-[#6b6b70]"}`}
            >
              {v.label}
            </button>
          ))}
        </div>
      </div>
      <div className="min-h-[360px] flex-1">
        {view === "map"
          ? <MapView warehouse={d.warehouse} supplier={d.supplier} shipment={d.shipment} />
          : <RippleMap data={d.ripple} />}
      </div>
      <div className="mt-3 grid grid-cols-2 overflow-hidden rounded-lg border border-[#e6e8ec] text-xs sm:grid-cols-4">
        {cells.map((c, i) => (
          <div key={c.label} className={`flex items-center justify-center gap-2 py-2 ${i > 0 ? "sm:border-l border-[#e6e8ec]" : ""}`}>
            <span className="size-2 rounded-full" style={{ background: c.color }} />
            <span className="text-[#55555a]">{c.label}</span>
            <b className="text-[#1c1c1e]">{c.n}</b>
          </div>
        ))}
      </div>
    </section>
  );
}
