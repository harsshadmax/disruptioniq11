"use client";

import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { Loader2, Play, Plus, RotateCcw, X } from "lucide-react";
import { toast } from "sonner";
import { api } from "@/lib/api/client";
import { allowed, CAN, type ScenarioEvent, type SimulationOptions, type SimulationResult as Result } from "@/lib/api/types";
import { useAuth } from "@/lib/auth";
import { useSimulationOptions } from "@/lib/queries";
import { SimulationResult } from "@/components/simulate/SimulationResult";
import { btnOutline, btnPrimary, Empty, ErrorBox, PageTitle, Panel } from "@/components/ui/bits";

const MAX_EVENTS = 6;
const KINDS = [
  { value: "supplier_shutdown", label: "Supplier shutdown" },
  { value: "shipment_delay", label: "Shipment delay" },
  { value: "demand_surge", label: "Demand surge" },
  { value: "stock_reduction", label: "Stock reduction" },
] as const;
type Kind = ScenarioEvent["kind"];

const field = "mt-1 block h-10 w-full rounded-xl border border-[#cfcac0] bg-white px-3 text-sm";

function describe(e: ScenarioEvent, o: SimulationOptions): string {
  const wh = (id: number | null) => (id == null ? "all warehouses" : o.warehouses.find((w) => w.id === id)?.name ?? `warehouse ${id}`);
  const sku = (id: number | null) => (id == null ? "all SKUs" : o.skus.find((s) => s.id === id)?.code ?? `SKU ${id}`);
  switch (e.kind) {
    case "supplier_shutdown": return `${o.suppliers.find((s) => s.id === e.supplier_id)?.name ?? "Supplier"} stops delivering`;
    case "shipment_delay": return `${o.shipments.find((s) => s.id === e.shipment_id)?.ref ?? "Shipment"} arrives ${e.days} day${e.days === 1 ? "" : "s"} late`;
    case "demand_surge": return `Orders +${e.percent}% for ${sku(e.sku_id)} at ${wh(e.warehouse_id)}`;
    case "stock_reduction": return `Stock -${e.percent}% for ${sku(e.sku_id)} at ${wh(e.warehouse_id)}`;
  }
}

export default function SimulatePage() {
  const { user } = useAuth();
  const canRun = allowed(CAN.simulate, user?.role);
  const options = useSimulationOptions(canRun);
  const [events, setEvents] = useState<ScenarioEvent[]>([]);
  const [kind, setKind] = useState<Kind>("supplier_shutdown");
  const [supplier, setSupplier] = useState("");
  const [shipment, setShipment] = useState("");
  const [days, setDays] = useState("5");
  const [percent, setPercent] = useState("30");
  const [warehouse, setWarehouse] = useState("");
  const [sku, setSku] = useState("");
  const [formError, setFormError] = useState<string | null>(null);
  const [result, setResult] = useState<{ data: Result; ranFor: string } | null>(null);

  const run = useMutation({
    mutationFn: () => api<Result>("/simulate/run", { body: { events } }),
    onSuccess: (data) => setResult({ data, ranFor: JSON.stringify(events) }),
    onError: (e) => toast.error(e instanceof Error ? e.message : "Simulation failed"),
  });

  if (!canRun) return (
    <>
      <PageTitle title="What-if lab" />
      <Empty>Your role works on one warehouse and cannot run network-wide simulations.</Empty>
    </>
  );
  if (options.isLoading) return (
    <>
      <PageTitle title="What-if lab" />
      <div className="h-40 animate-pulse rounded-2xl bg-white shadow-sm" aria-label="Loading the lab" />
    </>
  );
  if (options.error || !options.data) return <ErrorBox error={options.error} onRetry={() => options.refetch()} />;
  const o = options.data;

  const supplierId = Number(supplier || o.suppliers[0]?.id);
  const shipmentId = Number(shipment || o.shipments[0]?.id);
  const numOrNull = (v: string) => (v === "" ? null : Number(v));

  function add(e: ScenarioEvent) {
    if (events.length >= MAX_EVENTS) { setFormError(`A scenario holds at most ${MAX_EVENTS} events.`); return; }
    setFormError(null);
    setEvents((list) => [...list, e]);
  }

  function addFromForm() {
    const n = Number(kind === "shipment_delay" ? days : percent);
    if (!Number.isInteger(n)) { setFormError("Enter a whole number."); return; }
    if (kind === "supplier_shutdown") {
      if (!o.suppliers.length) { setFormError("There are no suppliers to shut down."); return; }
      add({ kind, supplier_id: supplierId });
    } else if (kind === "shipment_delay") {
      if (!o.shipments.length) { setFormError("There are no open shipments to delay."); return; }
      if (n < 1 || n > 90) { setFormError("A delay is between 1 and 90 days."); return; }
      add({ kind, shipment_id: shipmentId, days: n });
    } else {
      const max = kind === "demand_surge" ? 300 : 100;
      if (n < 1 || n > max) { setFormError(`The change is between 1% and ${max}%.`); return; }
      add({ kind, percent: n, warehouse_id: numOrNull(warehouse), sku_id: numOrNull(sku) });
    }
  }

  const stale = result !== null && result.ranFor !== JSON.stringify(events);

  return (
    <>
      <PageTitle
        title="What-if lab"
        sub="Try a disruption before it happens. The same allocation and risk rules as live detection are used, and nothing here changes real data."
      />

      <Panel title="Build a scenario" aside={`${events.length} of ${MAX_EVENTS} events`}>
        <div className="grid items-end gap-3 md:grid-cols-4">
          <label className="text-xs font-medium">What happens?
            <select value={kind} onChange={(e) => { setKind(e.target.value as Kind); setFormError(null); }} className={field}>
              {KINDS.map((k) => <option key={k.value} value={k.value}>{k.label}</option>)}
            </select>
          </label>

          {kind === "supplier_shutdown" && (
            <label className="text-xs font-medium md:col-span-2">Which supplier stops?
              <select value={supplierId || ""} onChange={(e) => setSupplier(e.target.value)} className={field}>
                {o.suppliers.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
              </select>
            </label>
          )}

          {kind === "shipment_delay" && (
            <>
              <label className="text-xs font-medium md:col-span-1">Which shipment?
                <select value={shipmentId || ""} onChange={(e) => setShipment(e.target.value)} className={field}>
                  {o.shipments.map((s) => <option key={s.id} value={s.id}>{s.ref} · {s.supplier} to {s.warehouse}</option>)}
                </select>
              </label>
              <label className="text-xs font-medium">Extra days late
                <input value={days} onChange={(e) => setDays(e.target.value)} inputMode="numeric" className={field} />
              </label>
            </>
          )}

          {(kind === "demand_surge" || kind === "stock_reduction") && (
            <>
              <label className="text-xs font-medium">{kind === "demand_surge" ? "Order quantity rises by (%)" : "On-hand stock falls by (%)"}
                <input value={percent} onChange={(e) => setPercent(e.target.value)} inputMode="numeric" className={field} />
              </label>
              <div className="grid grid-cols-2 gap-3">
                <label className="text-xs font-medium">Warehouse
                  <select value={warehouse} onChange={(e) => setWarehouse(e.target.value)} className={field}>
                    <option value="">All</option>
                    {o.warehouses.map((w) => <option key={w.id} value={w.id}>{w.name}</option>)}
                  </select>
                </label>
                <label className="text-xs font-medium">SKU
                  <select value={sku} onChange={(e) => setSku(e.target.value)} className={field}>
                    <option value="">All</option>
                    {o.skus.map((s) => <option key={s.id} value={s.id}>{s.code}</option>)}
                  </select>
                </label>
              </div>
            </>
          )}

          <button type="button" onClick={addFromForm} disabled={events.length >= MAX_EVENTS} className={btnOutline}>
            <Plus className="size-3.5" /> Add to scenario
          </button>
        </div>
        {formError && <p role="alert" className="mt-3 rounded-lg bg-[#f8e4e1] px-3 py-2 text-xs text-[#8c2a22]">{formError}</p>}

        <div className="mt-4 flex flex-wrap items-center gap-2 text-[11px] text-[#5c6670]">
          <span>Quick start:</span>
          <button type="button" className={btnOutline} onClick={() => add({ kind: "demand_surge", percent: 30, warehouse_id: null, sku_id: null })}>Orders +30% everywhere</button>
          <button type="button" className={btnOutline} onClick={() => add({ kind: "stock_reduction", percent: 25, warehouse_id: null, sku_id: null })}>Stock -25% everywhere</button>
        </div>

        <div className="mt-4 border-t border-[#ebe8e1] pt-3">
          <div className="mb-2 text-xs font-semibold text-[#1b2430]">This scenario</div>
          {events.length === 0 ? (
            <p className="text-xs text-[#6b7480]">Nothing yet. Add at least one event, then run the simulation. Events happen together.</p>
          ) : (
            <ul className="flex flex-col gap-1.5">
              {events.map((e, i) => (
                <li key={i} className="flex items-center justify-between gap-3 rounded-lg bg-[#f3f1ec] px-3 py-2 text-xs">
                  <span><b className="mr-2 text-brand-ink">{i + 1}</b>{describe(e, o)}</span>
                  <button type="button" aria-label={`Remove event ${i + 1}`} onClick={() => setEvents((l) => l.filter((_, j) => j !== i))}
                    className="flex size-6 items-center justify-center rounded-md text-[#6b7480] hover:bg-white"><X className="size-3.5" /></button>
                </li>
              ))}
            </ul>
          )}
          <div className="mt-3 flex flex-wrap gap-2">
            <button type="button" onClick={() => run.mutate()} disabled={events.length === 0 || run.isPending} className={btnPrimary}>
              {run.isPending ? <Loader2 className="size-3.5 animate-spin" /> : <Play className="size-3.5" />} Run simulation
            </button>
            <button type="button" onClick={() => { setEvents([]); setResult(null); setFormError(null); }} disabled={events.length === 0 && !result} className={btnOutline}>
              <RotateCcw className="size-3.5" /> Clear
            </button>
          </div>
        </div>
      </Panel>

      {result ? <SimulationResult result={result.data} stale={stale} /> : (
        <Empty>Build a scenario above and press <b>Run simulation</b>. You will see the real situation next to the simulated one.</Empty>
      )}
    </>
  );
}
