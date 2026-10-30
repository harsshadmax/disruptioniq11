"use client";

import Link from "next/link";
import { useState } from "react";
import { useSearch } from "@/components/app/AppShell";
import { Empty, ErrorBox, PageTitle, Panel, Pill, BAND_TONE, dayOf, inr, when } from "@/components/ui/bits";
import { useDisruptions } from "@/lib/queries";

const TYPE: Record<string, string> = { late_shipment: "Late shipment", supplier_delay: "Supplier delay", stock_shortage: "Stock shortage" };

export default function DisruptionsPage() {
  const [state, setState] = useState<"active" | "resolved" | "all">("active");
  const { query } = useSearch();
  const list = useDisruptions(state);
  const q = query.trim().toLowerCase();
  const rows = (list.data ?? []).filter((d) =>
    !q || [d.shipment_ref, `dis-${d.id}`, d.sku_code, d.sku_name, d.warehouse, d.supplier].join(" ").toLowerCase().includes(q));

  return (
    <>
      <PageTitle title="Disruptions" sub="Every delayed shipment or stock gap the rules found, ranked by risk."
        actions={
          <select value={state} onChange={(e) => setState(e.target.value as typeof state)} aria-label="Status filter"
            className="h-9 rounded-full border border-[#d9d9de] bg-white px-4 text-xs font-medium">
            <option value="active">Active</option><option value="resolved">Resolved</option><option value="all">All</option>
          </select>
        } />
      {list.error && <ErrorBox error={list.error} onRetry={() => list.refetch()} />}
      {list.isLoading && <div className="h-64 animate-pulse rounded-2xl bg-white" />}
      {list.data && rows.length === 0 && <Empty>{q ? "No disruption matches that search." : "No disruptions in this view."}</Empty>}
      {rows.length > 0 && (
        <Panel>
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs">
              <thead className="text-[10px] uppercase tracking-wide text-[#8a8a8f]">
                <tr>{["Ref", "Type", "Severity", "Where", "Shipment / supplier", "Orders at risk", "Penalty exposure", "Detected"].map((h) => <th key={h} className="px-3 py-2 font-medium">{h}</th>)}</tr>
              </thead>
              <tbody>
                {rows.map((d) => (
                  <tr key={d.id} className="border-t border-[#f0f0f2] hover:bg-[#fafafb]">
                    <td className="px-3 py-3 font-semibold"><Link className="text-brand" href={`/disruptions/${d.id}`}>DIS-{d.id}</Link></td>
                    <td className="px-3 py-3">{TYPE[d.type] ?? d.type}</td>
                    <td className="px-3 py-3"><Pill tone={BAND_TONE[d.severity]}>{d.severity}</Pill>{d.status !== "active" && <span className="ml-2 text-[10px] text-[#8a8a8f]">{d.status}</span>}</td>
                    <td className="px-3 py-3">{d.warehouse} · {d.sku_code}</td>
                    <td className="px-3 py-3">{d.shipment_ref ?? "n/a"}<div className="text-[10px] text-[#8a8a8f]">{d.supplier ?? ""}</div></td>
                    <td className="px-3 py-3">{d.orders_at_risk}{d.newly_at_risk > 0 && <span className="ml-1 text-[10px] text-[#e5384f]">({d.newly_at_risk} new)</span>}</td>
                    <td className="px-3 py-3">{inr(d.penalty_exposure)}</td>
                    <td className="px-3 py-3 text-[#6b6b70]">{when(d.detected_at)} <span className="text-[#aaa]">({dayOf(d.detected_at)})</span></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Panel>
      )}
    </>
  );
}
