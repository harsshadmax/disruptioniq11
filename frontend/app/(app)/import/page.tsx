"use client";

import { useRef, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Download, Loader2, Upload } from "lucide-react";
import { toast } from "sonner";
import { api } from "@/lib/api/client";
import { allowed, CAN, type ImportResult } from "@/lib/api/types";
import { useAuth } from "@/lib/auth";
import { useBatches } from "@/lib/queries";
import { btnOutline, btnPrimary, Empty, PageTitle, Panel, Pill } from "@/components/ui/bits";

const ENTITIES = {
  orders: ["order_ref", "customer", "order_date", "due_date", "sku", "warehouse", "qty", "sla_penalty"],
  inventory: ["warehouse", "sku", "on_hand", "safety_stock"],
  shipments: ["shipment_ref", "supplier", "carrier", "dest_warehouse", "promised_eta", "sku", "qty"],
} as const;
type Entity = keyof typeof ENTITIES;

function template(entity: Entity) {
  const url = URL.createObjectURL(new Blob([ENTITIES[entity].join(",") + "\n"], { type: "text/csv" }));
  const a = document.createElement("a");
  a.href = url; a.download = `${entity}-template.csv`; a.click();
  URL.revokeObjectURL(url);
}

export default function ImportPage() {
  const { user } = useAuth();
  const canImport = allowed(CAN.importData, user?.role);
  const qc = useQueryClient();
  const batches = useBatches();
  const [entity, setEntity] = useState<Entity>("orders");
  const [file, setFile] = useState<File | null>(null);
  const [result, setResult] = useState<ImportResult | null>(null);
  const input = useRef<HTMLInputElement>(null);

  const upload = useMutation({
    mutationFn: () => {
      const form = new FormData();
      form.append("file", file as File);
      return api<ImportResult>("/import/csv", { method: "POST", form, params: { entity } });
    },
    onSuccess: (r) => {
      setResult(r);
      if (r.rows_failed) toast.warning(`${r.rows_ok} rows imported, ${r.rows_failed} rejected.`);
      else toast.success(`${r.rows_ok} rows imported.`);
      qc.invalidateQueries();
    },
  });

  return (
    <>
      <PageTitle title="Import data" sub="Good rows are imported even when others fail. Every rejected row comes back with its reason." />
      {!canImport && <Empty>Your role can view past imports but cannot run one.</Empty>}
      {canImport && (
        <Panel title="Upload a CSV">
          <div className="flex flex-wrap items-end gap-3">
            <label className="text-xs font-medium">What are you importing?
              <select value={entity} onChange={(e) => { setEntity(e.target.value as Entity); setResult(null); }}
                className="mt-1 block h-10 rounded-xl border border-[#cfcac0] bg-white px-3 text-sm">
                {Object.keys(ENTITIES).map((k) => <option key={k}>{k}</option>)}
              </select>
            </label>
            <label className="text-xs font-medium">CSV file
              <input ref={input} type="file" accept=".csv,text/csv" onChange={(e) => { setFile(e.target.files?.[0] ?? null); setResult(null); }}
                className="mt-1 block h-10 rounded-xl border border-[#cfcac0] bg-white px-3 py-2 text-xs" />
            </label>
            <button onClick={() => upload.mutate()} disabled={!file || upload.isPending} className={btnPrimary}>
              {upload.isPending ? <Loader2 className="size-3.5 animate-spin" /> : <Upload className="size-3.5" />} Import
            </button>
            <button onClick={() => template(entity)} className={btnOutline}><Download className="size-3.5" /> Template</button>
          </div>
          <p className="mt-3 text-[11px] text-[#6b7480]">Columns for {entity}: <code>{ENTITIES[entity].join(", ")}</code>. Maximum 10 MB and 10,000 rows. A timestamp without a timezone is read as UTC.</p>
          {upload.error && <p role="alert" className="mt-3 rounded-lg bg-[#f8e4e1] px-3 py-2 text-xs text-[#8c2a22]">{(upload.error as Error).message}</p>}
        </Panel>
      )}

      {result && (
        <Panel title={`Result for batch #${result.batch_id}`} aside={result.filename ?? undefined}>
          <div className="flex gap-3 text-xs">
            <Pill tone="bg-[#ece9e2] text-[#555]">{result.rows_total} rows</Pill>
            <Pill tone="bg-[#e3f0e7] text-[#2e7d4f]">{result.rows_ok} imported</Pill>
            <Pill tone={result.rows_failed ? "bg-[#f8e4e1] text-[#c8352b]" : undefined}>{result.rows_failed} rejected</Pill>
          </div>
          {result.errors.length > 0 && (
            <div className="mt-3 max-h-80 overflow-auto">
              <table className="w-full text-left text-xs">
                <thead className="text-[10px] uppercase tracking-wide text-[#6b7480]"><tr><th className="px-3 py-2">Row</th><th className="px-3 py-2">Field</th><th className="px-3 py-2">Why it was rejected</th></tr></thead>
                <tbody>{result.errors.map((e, i) => (
                  <tr key={i} className="border-t border-[#ebe8e1]"><td className="px-3 py-2">{e.row_no}</td><td className="px-3 py-2">{e.field ?? ""}</td><td className="px-3 py-2">{e.reason}</td></tr>))}</tbody>
              </table>
            </div>)}
        </Panel>
      )}

      <Panel title="Recent imports">
        {!batches.data?.length ? <p className="text-xs text-[#6b7480]">No imports yet. Seeded demo data is not listed here.</p> : (
          <table className="w-full text-left text-xs">
            <thead className="text-[10px] uppercase tracking-wide text-[#6b7480]"><tr>{["Batch", "Entity", "Source", "File", "Imported", "Rejected"].map((h) => <th key={h} className="px-3 py-2 font-medium">{h}</th>)}</tr></thead>
            <tbody>{batches.data.map((b) => (
              <tr key={b.batch_id} className="border-t border-[#ebe8e1] cursor-pointer hover:bg-[#f8f6f2]" onClick={() => setResult(b)}>
                <td className="px-3 py-2">#{b.batch_id}</td><td className="px-3 py-2">{b.entity}</td><td className="px-3 py-2">{b.source}</td>
                <td className="px-3 py-2">{b.filename ?? ""}</td><td className="px-3 py-2">{b.rows_ok}</td><td className="px-3 py-2">{b.rows_failed}</td></tr>))}</tbody>
          </table>)}
      </Panel>
    </>
  );
}
