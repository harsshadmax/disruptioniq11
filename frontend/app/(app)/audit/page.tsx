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
          <span className={`flex items-center gap-2 rounded-lg px-4 py-2 text-xs font-semibold ${verify.data.ok ? "bg-[#e3f0e7] text-[#2e7d4f]" : "bg-[#f8e4e1] text-[#c8352b]"}`}>
            {verify.data.ok ? <ShieldCheck className="size-4" /> : <ShieldAlert className="size-4" />}
            {verify.data.ok ? `Chain intact (${verify.data.rows_checked} rows)` : `Broken at row ${verify.data.first_bad_id}`}
          </span>)} />
      <div className="flex flex-wrap gap-2">
        <select value={action} onChange={(e) => setAction(e.target.value)} aria-label="Action filter" className="h-9 rounded-lg border border-[#cfcac0] bg-white px-4 text-xs">
          <option value="">All actions</option>{actions.map((a) => <option key={a}>{a}</option>)}</select>
        <select value={entity} onChange={(e) => setEntity(e.target.value)} aria-label="Entity filter" className="h-9 rounded-lg border border-[#cfcac0] bg-white px-4 text-xs">
          <option value="">All entities</option>{entities.map((a) => <option key={a}>{a}</option>)}</select>
        <input value={text} onChange={(e) => setText(e.target.value)} placeholder="Search reason, id or details" aria-label="Search the log"
          className="h-9 min-w-56 flex-1 rounded-lg border border-[#cfcac0] bg-white px-4 text-xs outline-none focus:border-brand" />
      </div>
      {rows.isLoading && <div className="h-64 animate-pulse rounded-2xl bg-white" />}
      {rows.data && shown.length === 0 && <Empty>No entries match.</Empty>}
      {shown.length > 0 && (
        <Panel>
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs">
              <thead className="text-[10px] uppercase tracking-wide text-[#6b7480]"><tr>
                {["#", "Time", "Who", "Action", "Entity", "Reason"].map((h) => <th key={h} className="px-3 py-2 font-medium">{h}</th>)}</tr></thead>
              <tbody>{shown.map((r) => (
                <Fragment key={r.id}>
                  <tr onClick={() => setOpen(open === r.id ? null : r.id)} className="cursor-pointer border-t border-[#ebe8e1] hover:bg-[#f8f6f2]">
                    <td className="px-3 py-2 text-[#6b7480]">{r.id}</td><td className="whitespace-nowrap px-3 py-2">{when(r.ts)}</td>
                    <td className="px-3 py-2">{r.role ? ROLE_LABEL[r.role] ?? r.role : "System"}{r.actor_id ? <span className="text-[#6b7480]"> #{r.actor_id}</span> : null}</td>
                    <td className="px-3 py-2"><Pill tone={BLOCKED.test(r.action) ? "bg-[#f8e4e1] text-[#c8352b]" : undefined}>{r.action}</Pill></td>
                    <td className="px-3 py-2">{r.entity_type}{r.entity_id ? ` ${r.entity_id}` : ""}</td>
                    <td className="max-w-xs truncate px-3 py-2 text-[#4a545e]">{r.reason ?? ""}</td>
                  </tr>
                  {open === r.id && (
                    <tr className="bg-[#f8f6f2]"><td colSpan={6} className="px-3 py-3">
                      <pre className="overflow-x-auto whitespace-pre-wrap text-[11px] text-[#2f3944]">{JSON.stringify(r.payload, null, 2)}</pre>
                      <p className="mt-1 break-all font-mono text-[10px] text-[#6b7480]">hash {r.row_hash}</p>
                    </td></tr>)}
                </Fragment>))}</tbody>
            </table>
          </div>
        </Panel>)}
    </>
  );
}
