"use client";

import { Fragment, useMemo, useState } from "react";
import { ShieldCheck, ShieldAlert } from "lucide-react";
import { allowed, CAN, ROLE_LABEL } from "@/lib/api/types";
import { useAuth } from "@/lib/auth";
import { useAudit, useAuditVerify } from "@/lib/queries";
import { Empty, ErrorBox, PageTitle, Panel, Pill, when } from "@/components/ui/bits";

const BLOCKED = /blocked|denied|failed|rejected|stale/;

export default function AuditPage() {
  const { user } = useAuth();
  const ok = allowed(CAN.readAudit, user?.role);
  const [action, setAction] = useState("");
  const [entity, setEntity] = useState("");
  const [text, setText] = useState("");
  const rows = useAudit(action, entity, ok);
  const verify = useAuditVerify(ok);
  const [open, setOpen] = useState<number | null>(null);

  // Filter choices come from what is actually in the log; the chosen one is also sent to the server.
  const known = useAudit("", "", ok);
  const actions = useMemo(() => [...new Set((known.data ?? []).map((r) => r.action))].sort(), [known.data]);
  const entities = useMemo(() => [...new Set((known.data ?? []).map((r) => r.entity_type))].sort(), [known.data]);

  if (!ok) return <><PageTitle title="Audit log" /><Empty>Your role cannot read the audit log.</Empty></>;
  if (rows.error) return <ErrorBox error={rows.error} onRetry={() => rows.refetch()} />;

  const t = text.trim().toLowerCase();
  const shown = (rows.data ?? []).filter((r) => !t || JSON.stringify([r.action, r.entity_id, r.reason, r.role, r.payload]).toLowerCase().includes(t));

  return (
    <>
      <PageTitle title="Audit log" sub="Append-only and hash-chained. Blocked attempts are recorded too."
        actions={verify.data && (
          <span className={`flex items-center gap-2 rounded-full px-4 py-2 text-xs font-semibold ${verify.data.ok ? "bg-[#e6f6ea] text-[#16a34a]" : "bg-[#fdecee] text-[#e5384f]"}`}>
            {verify.data.ok ? <ShieldCheck className="size-4" /> : <ShieldAlert className="size-4" />}
            {verify.data.ok ? `Chain intact (${verify.data.rows_checked} rows)` : `Broken at row ${verify.data.first_bad_id}`}
          </span>)} />
      <div className="flex flex-wrap gap-2">
        <select value={action} onChange={(e) => setAction(e.target.value)} aria-label="Action filter" className="h-9 rounded-full border border-[#d9d9de] bg-white px-4 text-xs">
          <option value="">All actions</option>{actions.map((a) => <option key={a}>{a}</option>)}</select>
        <select value={entity} onChange={(e) => setEntity(e.target.value)} aria-label="Entity filter" className="h-9 rounded-full border border-[#d9d9de] bg-white px-4 text-xs">
          <option value="">All entities</option>{entities.map((a) => <option key={a}>{a}</option>)}</select>
        <input value={text} onChange={(e) => setText(e.target.value)} placeholder="Search reason, id or details" aria-label="Search the log"
          className="h-9 min-w-56 flex-1 rounded-full border border-[#d9d9de] bg-white px-4 text-xs outline-none focus:border-[#e5384f]" />
      </div>
      {rows.isLoading && <div className="h-64 animate-pulse rounded-2xl bg-white" />}
      {rows.data && shown.length === 0 && <Empty>No entries match.</Empty>}
      {shown.length > 0 && (
        <Panel>
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs">
              <thead className="text-[10px] uppercase tracking-wide text-[#8a8a8f]"><tr>
                {["#", "Time", "Who", "Action", "Entity", "Reason"].map((h) => <th key={h} className="px-3 py-2 font-medium">{h}</th>)}</tr></thead>
              <tbody>{shown.map((r) => (
                <Fragment key={r.id}>
                  <tr onClick={() => setOpen(open === r.id ? null : r.id)} className="cursor-pointer border-t border-[#f0f0f2] hover:bg-[#fafafb]">
                    <td className="px-3 py-2 text-[#8a8a8f]">{r.id}</td><td className="whitespace-nowrap px-3 py-2">{when(r.ts)}</td>
                    <td className="px-3 py-2">{r.role ? ROLE_LABEL[r.role] ?? r.role : "System"}{r.actor_id ? <span className="text-[#8a8a8f]"> #{r.actor_id}</span> : null}</td>
                    <td className="px-3 py-2"><Pill tone={BLOCKED.test(r.action) ? "bg-[#fdecee] text-[#e5384f]" : undefined}>{r.action}</Pill></td>
                    <td className="px-3 py-2">{r.entity_type}{r.entity_id ? ` ${r.entity_id}` : ""}</td>
                    <td className="max-w-xs truncate px-3 py-2 text-[#55555a]">{r.reason ?? ""}</td>
                  </tr>
                  {open === r.id && (
                    <tr className="bg-[#fafafb]"><td colSpan={6} className="px-3 py-3">
                      <pre className="overflow-x-auto whitespace-pre-wrap text-[11px] text-[#3a3a3f]">{JSON.stringify(r.payload, null, 2)}</pre>
                      <p className="mt-1 break-all font-mono text-[10px] text-[#8a8a8f]">hash {r.row_hash}</p>
                    </td></tr>)}
                </Fragment>))}</tbody>
            </table>
          </div>
        </Panel>)}
    </>
  );
}
