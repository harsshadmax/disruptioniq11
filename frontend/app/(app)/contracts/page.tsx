"use client";

import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { BadgeCheck, FileSearch, Loader2, ShieldCheck, Upload, X } from "lucide-react";
import { toast } from "sonner";
import { api, ApiError } from "@/lib/api/client";
import { allowed, CAN, type AiCheck, type Contract, type ContractConfirmResult, type ContractPreview, type ContractTerms } from "@/lib/api/types";
import { useAuth } from "@/lib/auth";
import { useContractCustomers, useContracts } from "@/lib/queries";
import { btnOutline, btnPrimary, Empty, ErrorBox, inr, PageTitle, Panel, Pill, when } from "@/components/ui/bits";

const STATUS_TONE: Record<string, string> = {
  pending: "bg-[#f8ecd3] text-[#c77700]", confirmed: "bg-[#e3f0e7] text-[#2e7d4f]",
  superseded: "bg-[#ece9e2] text-[#555]", rejected: "bg-[#f8e4e1] text-[#c8352b]",
};
const VERDICT = {
  supported: ["Supported", "bg-[#e3f0e7] text-[#2e7d4f]"], contradicted: ["Differs", "bg-[#f8e4e1] text-[#c8352b]"],
  not_found: ["Not found", "bg-[#f8ecd3] text-[#c77700]"], unverified: ["No evidence", "bg-[#ece9e2] text-[#555]"],
} as const;

type Num = "flat_amount" | "rate_percent" | "cap_percent" | "cap_amount" | "grace_days" | "termination_days";
const NUMBER_FIELDS: { key: Num; label: string; hint: string }[] = [
  { key: "flat_amount", label: "Fixed penalty per late order (₹)", hint: "A set amount per late order" },
  { key: "rate_percent", label: "Penalty rate (% of order value)", hint: "Charged for each day or week of delay" },
  { key: "cap_percent", label: "Penalty cap (% of order value)", hint: "The most the contract can charge" },
  { key: "cap_amount", label: "Penalty cap (₹)", hint: "The most the contract can charge" },
  { key: "grace_days", label: "Grace period (days)", hint: "Delay allowed before any penalty" },
  { key: "termination_days", label: "Customer may cancel after (days of delay)", hint: "Cancellation right" },
];

type Form = Record<Num, string> & { rate_period: string; force_majeure: string };
const toForm = (t: ContractTerms): Form => ({
  ...Object.fromEntries(NUMBER_FIELDS.map((f) => [f.key, t[f.key] == null ? "" : String(t[f.key])])) as Record<Num, string>,
  rate_period: t.rate_period ?? "", force_majeure: t.force_majeure == null ? "" : t.force_majeure ? "yes" : "no",
});
const toTerms = (f: Form): ContractTerms => ({
  ...Object.fromEntries(NUMBER_FIELDS.map((n) => [n.key, f[n.key].trim() === "" || Number.isNaN(Number(f[n.key])) ? null : Number(f[n.key])])) as Record<Num, number | null>,
  rate_period: f.rate_period || null, force_majeure: f.force_majeure === "" ? null : f.force_majeure === "yes",
});

function useDebounced<T>(value: T, ms = 400): T {
  const [v, setV] = useState(value);
  useEffect(() => { const t = setTimeout(() => setV(value), ms); return () => clearTimeout(t); }, [value, ms]);
  return v;
}

const summary = (t: ContractTerms) => [
  t.flat_amount != null && `${inr(t.flat_amount)} per late order`,
  t.rate_percent != null && `${t.rate_percent}% per ${t.rate_period ?? "period"}`,
  t.cap_percent != null && `cap ${t.cap_percent}%`,
  t.cap_amount != null && `cap ${inr(t.cap_amount)}`,
  t.grace_days != null && `${t.grace_days} days grace`,
].filter(Boolean).join(" · ") || "No penalty terms";

export default function ContractsPage() {
  const { user } = useAuth();
  const canUpload = allowed(CAN.contractUpload, user?.role);
  const contracts = useContracts();
  const [openId, setOpenId] = useState<number | null>(null);
  const open = contracts.data?.find((c) => c.id === openId && c.status === "pending");

  return (
    <>
      <PageTitle title="Contracts" sub="Upload a customer contract, check the penalty terms the app read from it, then confirm. Confirmed terms replace that customer's penalty in risk scores, exposure and the What-if lab." />
      {canUpload && <UploadPanel onRead={(c) => setOpenId(c.id)} />}
      {open && <Review key={open.id} contract={open} onDone={() => setOpenId(null)} />}
      <Panel title="Contracts on file" aside="Only confirmed contracts change any number">
        {contracts.error && <ErrorBox error={contracts.error} onRetry={() => contracts.refetch()} />}
        {contracts.isLoading && <div className="h-24 animate-pulse rounded-xl bg-[#f3f1ec]" />}
        {contracts.data?.length === 0 && <p className="text-xs text-[#6b7480]">No contract has been uploaded yet. A sample is in the repository under docs/samples.</p>}
        {!!contracts.data?.length && (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs">
              <thead className="text-[10px] uppercase tracking-wide text-[#6b7480]"><tr>
                {["Customer", "File", "Status", "Terms", "Uploaded", ""].map((h) => <th key={h} className="px-3 py-2 font-medium">{h}</th>)}</tr></thead>
              <tbody>{contracts.data.map((c) => (
                <tr key={c.id} className="border-t border-[#ebe8e1]">
                  <td className="px-3 py-2 font-semibold">{c.customer}</td>
                  <td className="px-3 py-2 text-[#5c6670]">{c.filename}</td>
                  <td className="px-3 py-2"><Pill tone={STATUS_TONE[c.status]}>{c.status}</Pill></td>
                  <td className="px-3 py-2">{summary(c.terms)}</td>
                  <td className="px-3 py-2 text-[#5c6670]">{when(c.uploaded_at)}{c.uploaded_by && ` · ${c.uploaded_by}`}</td>
                  <td className="px-3 py-2 text-right">{c.status === "pending" && <button onClick={() => setOpenId(c.id)} className={btnOutline}>Review</button>}</td>
                </tr>))}</tbody>
            </table>
          </div>)}
      </Panel>
    </>
  );
}

function UploadPanel({ onRead }: { onRead: (c: Contract) => void }) {
  const qc = useQueryClient();
  const customers = useContractCustomers();
  const [customerId, setCustomerId] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const input = useRef<HTMLInputElement>(null);
  const read = useMutation({
    mutationFn: () => {
      const form = new FormData();
      form.append("customer_id", customerId);
      form.append("file", file as File);
      return api<Contract>("/contracts/upload", { method: "POST", form });
    },
    onSuccess: (c) => {
      toast.success(`Contract read: ${c.findings.length} clause${c.findings.length === 1 ? "" : "s"} found. Check them below.`);
      setFile(null);
      if (input.current) input.current.value = "";
      qc.invalidateQueries({ queryKey: ["contracts"] });
      onRead(c);
    },
  });
  return (
    <Panel title="Upload a contract (PDF)">
      <div className="flex flex-wrap items-end gap-3">
        <label className="text-xs font-medium">Customer
          <select value={customerId} onChange={(e) => setCustomerId(e.target.value)} className="mt-1 block h-10 min-w-56 rounded-xl border border-[#cfcac0] bg-white px-3 text-sm">
            <option value="">Choose a customer</option>
            {customers.data?.map((c) => <option key={c.id} value={c.id}>{c.name} · {c.tier} · {c.open_orders} open{c.contract_id ? " · has contract" : ""}</option>)}
          </select>
        </label>
        <label className="text-xs font-medium">PDF file
          <input ref={input} type="file" accept="application/pdf,.pdf" onChange={(e) => setFile(e.target.files?.[0] ?? null)}
            className="mt-1 block h-10 rounded-xl border border-[#cfcac0] bg-white px-3 py-2 text-xs" />
        </label>
        <button onClick={() => read.mutate()} disabled={!customerId || !file || read.isPending} className={btnPrimary}>
          {read.isPending ? <Loader2 className="size-3.5 animate-spin" /> : <Upload className="size-3.5" />} Read contract
        </button>
      </div>
      <p className="mt-3 text-[11px] text-[#6b7480]">Text-based PDFs up to 5 MB (scans are not read). The app looks for penalty rates, caps, fixed amounts, grace periods and cancellation rights, and shows the sentence each came from. Nothing changes until a Supply Chain Manager confirms.</p>
      {read.error && <p role="alert" className="mt-3 rounded-lg bg-[#f8e4e1] px-3 py-2 text-xs text-[#8c2a22]">{(read.error as Error).message}</p>}
    </Panel>
  );
}

function Review({ contract, onDone }: { contract: Contract; onDone: () => void }) {
  const { user } = useAuth();
  const qc = useQueryClient();
  const canConfirm = allowed(CAN.contractConfirm, user?.role);
  const canCheck = allowed(CAN.contractUpload, user?.role);
  const [form, setForm] = useState<Form>(() => toForm(contract.terms));
  const [ai, setAi] = useState<AiCheck | null>((contract.ai_check as AiCheck | null) ?? null);
  const [blocked, setBlocked] = useState<AiCheck | null>(null);
  const terms = toTerms(form);
  const debounced = useDebounced(JSON.stringify(terms));
  const set = (k: keyof Form, v: string) => { setForm((f) => ({ ...f, [k]: v })); setBlocked(null); };
  const snippetOf = (field: string) => contract.findings.find((f) => f.field === field)?.snippet;

  const preview = useQuery({
    queryKey: ["contracts", "preview", contract.id, debounced],
    queryFn: () => api<ContractPreview>(`/contracts/${contract.id}/preview`, { method: "POST", body: JSON.parse(debounced) }),
    placeholderData: (prev) => prev,
  });
  const check = useMutation({
    mutationFn: () => api<AiCheck>(`/contracts/${contract.id}/check`, { method: "POST", body: terms }),
    onSuccess: (r) => { setAi(r); setBlocked(null); },
  });
  const confirm = useMutation({
    mutationFn: (override: boolean) => api<ContractConfirmResult>(`/contracts/${contract.id}/confirm`, { method: "POST", body: { terms, override_ai: override } }),
    onSuccess: (r) => {
      toast.success(`Contract confirmed for ${r.contract.customer}. Risk and penalty exposure were recalculated${r.disruptions_updated ? ` (${r.disruptions_updated} disruption${r.disruptions_updated === 1 ? "" : "s"} updated)` : ""}.`);
      qc.invalidateQueries();
      onDone();
    },
    onError: (e) => {
      const detail = e instanceof ApiError ? (e.detail as { ai_check?: AiCheck } | undefined) : undefined;
      if (detail?.ai_check) { setBlocked(detail.ai_check); setAi(detail.ai_check); }
    },
  });
  const reject = useMutation({
    mutationFn: () => api<Contract>(`/contracts/${contract.id}/reject`, { method: "POST" }),
    onSuccess: () => { toast.info("Contract rejected. Nothing was changed."); qc.invalidateQueries({ queryKey: ["contracts"] }); onDone(); },
  });
  const busy = confirm.isPending || reject.isPending;
  const p = preview.data;

  return (
    <Panel title={`Review terms: ${contract.customer}`} aside={<span className="flex items-center gap-2">{contract.filename}<Pill tone={STATUS_TONE.pending}>pending</Pill></span>}>
      {contract.warnings.map((w) => <p key={w} className="mb-2 rounded-lg bg-[#f8ecd3] px-3 py-2 text-xs text-[#8a5a00]">{w}</p>)}
      <div className="grid gap-3 md:grid-cols-2">
        {NUMBER_FIELDS.map((f) => (
          <label key={f.key} className="block rounded-xl border border-[#ebe8e1] p-3 text-xs font-medium">
            <span className="flex items-center justify-between gap-2">{f.label}{snippetOf(f.key) ? <Pill tone="bg-[#e4ecf6] text-[#163a6b]">Found</Pill> : <Pill>Not found</Pill>}</span>
            <input type="number" min={0} step="any" value={form[f.key]} onChange={(e) => set(f.key, e.target.value)} placeholder="Not stated"
              className="mt-2 block h-9 w-full rounded-lg border border-[#cfcac0] bg-white px-3 text-sm" />
            <span className="mt-1 block text-[11px] font-normal italic text-[#6b7480]">{snippetOf(f.key) ? `"${snippetOf(f.key)}"` : f.hint}</span>
          </label>
        ))}
        <label className="block rounded-xl border border-[#ebe8e1] p-3 text-xs font-medium">
          Rate applies per
          <select value={form.rate_period} onChange={(e) => set("rate_period", e.target.value)} className="mt-2 block h-9 w-full rounded-lg border border-[#cfcac0] bg-white px-3 text-sm">
            <option value="">Not stated</option><option value="day">Day of delay</option><option value="week">Week of delay</option>
          </select>
        </label>
        <label className="block rounded-xl border border-[#ebe8e1] p-3 text-xs font-medium">
          Force majeure clause
          <select value={form.force_majeure} onChange={(e) => set("force_majeure", e.target.value)} className="mt-2 block h-9 w-full rounded-lg border border-[#cfcac0] bg-white px-3 text-sm">
            <option value="">Not stated</option><option value="yes">Present</option><option value="no">Absent</option>
          </select>
          {snippetOf("force_majeure") && <span className="mt-1 block text-[11px] font-normal italic text-[#6b7480]">&quot;{snippetOf("force_majeure")}&quot;</span>}
        </label>
      </div>

      <div className="mt-4 rounded-xl bg-[#f1f5fa] p-3 text-xs">
        <div className="font-semibold text-[#163a6b]">What this changes</div>
        {!p ? <div className="mt-2 h-10 animate-pulse rounded bg-white/70" /> : (
          <>
            <p className="mt-1 text-[#2f3944]">
              {p.order_count} open order{p.order_count === 1 ? "" : "s"}: penalty at stake {inr(p.current_total)} now
              {p.has_ceiling ? <> and <b>{inr(p.contract_total)}</b> under these terms.</> : <>. These terms name no cap or fixed amount, so the orders keep their own penalty.</>}
            </p>
            {p.has_ceiling && <p className="mt-1 text-[11px] text-[#5c6670]">Exposure uses the most the contract can charge for one late order (the lower of the fixed amount and the caps), because the final delay is not known yet.</p>}
            {p.orders.length > 0 && p.has_ceiling && (
              <table className="mt-2 w-full text-left text-[11px]">
                <thead className="text-[10px] uppercase tracking-wide text-[#6b7480]"><tr><th className="py-1 pr-3 font-medium">Order</th><th className="py-1 pr-3 font-medium">Value</th><th className="py-1 pr-3 font-medium">Now</th><th className="py-1 font-medium">Under contract</th></tr></thead>
                <tbody>{p.orders.slice(0, 5).map((o) => (
                  <tr key={o.order_ref} className="border-t border-[#dbe4ef]"><td className="py-1 pr-3 font-semibold">{o.order_ref}</td><td className="py-1 pr-3">{inr(o.value)}</td><td className="py-1 pr-3">{inr(o.current_penalty)}</td><td className="py-1">{inr(o.contract_penalty)}</td></tr>))}</tbody>
              </table>)}
          </>)}
      </div>

      <div className="mt-4 rounded-xl border border-[#ebe8e1] p-3 text-xs">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="flex items-center gap-2 font-semibold"><ShieldCheck className="size-4 text-brand" /> AI check <span className="font-normal text-[#6b7480]">second opinion; it cannot change a figure</span></div>
          {canCheck && <button onClick={() => check.mutate()} disabled={check.isPending || busy} className={btnOutline}>
            {check.isPending ? <Loader2 className="size-3.5 animate-spin" /> : <FileSearch className="size-3.5" />} Check with AI</button>}
        </div>
        {check.error && <p role="alert" className="mt-2 text-[#8c2a22]">{(check.error as Error).message}</p>}
        {!ai && <p className="mt-2 text-[#6b7480]">Not run yet. Confirming also runs it on the final values.</p>}
        {ai && !ai.available && <p className="mt-2 text-[#6b7480]">Not available: {ai.reason}</p>}
        {ai?.available && (
          <div className="mt-2 space-y-2">
            <p className="text-[#2f3944]">{ai.summary} <span className="text-[#6b7480]">({ai.provider === "free-llm" ? ai.model : `Claude ${ai.model}`})</span></p>
            {ai.checks.map((c) => (
              <div key={c.field} className="flex flex-wrap items-baseline gap-2">
                <Pill tone={VERDICT[c.verdict][1]}>{VERDICT[c.verdict][0]}</Pill>
                <span className="font-medium">{c.label}: {String(c.value)}</span>
                {c.quote && <span className="italic text-[#6b7480]">&quot;{c.quote}&quot;</span>}
              </div>))}
            {ai.missed.length > 0 && <div><div className="font-medium">Also in the contract, not in the terms above:</div>
              {ai.missed.map((m) => <div key={m.quote} className="italic text-[#6b7480]">{m.what}: &quot;{m.quote}&quot;</div>)}</div>}
            <p className="text-[10px] text-[#6b7480]">Only the delay and penalty sentences are sent to the AI service, never the whole contract. Free services may keep what they receive.</p>
          </div>)}
      </div>

      {blocked?.available && (
        <div role="alert" className="mt-4 rounded-xl bg-[#f8e4e1] p-3 text-xs text-[#8c2a22]">
          <div className="font-semibold">The AI check found the contract says something different</div>
          <p className="mt-1">Fix the highlighted values, or confirm anyway if you are sure. Confirming anyway is recorded in the audit log.</p>
          <button onClick={() => confirm.mutate(true)} disabled={busy} className="mt-2 rounded-lg border border-[#c8352b] bg-white px-3 py-1.5 text-xs font-semibold">Confirm anyway</button>
        </div>)}
      {confirm.error && !blocked && <p role="alert" className="mt-3 rounded-lg bg-[#f8e4e1] px-3 py-2 text-xs text-[#8c2a22]">{(confirm.error as Error).message}</p>}

      <div className="mt-4 flex flex-wrap items-center gap-2">
        {canConfirm ? (
          <>
            <button onClick={() => confirm.mutate(false)} disabled={busy} className={btnPrimary}>
              {confirm.isPending ? <Loader2 className="size-3.5 animate-spin" /> : <BadgeCheck className="size-3.5" />} Confirm terms
            </button>
            <button onClick={() => reject.mutate()} disabled={busy} className={btnOutline}><X className="size-3.5" /> Reject contract</button>
          </>
        ) : <Empty>A Supply Chain Manager has to confirm these terms before they count. You can still correct the values and run the AI check.</Empty>}
      </div>
    </Panel>
  );
}
