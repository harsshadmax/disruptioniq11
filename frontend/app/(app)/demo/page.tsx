"use client";

import Link from "next/link";
import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, Loader2, Play, ShieldAlert } from "lucide-react";
import { toast } from "sonner";
import { api } from "@/lib/api/client";
import { allowed, CAN, ROLE_LABEL, type DemoResult } from "@/lib/api/types";
import { useAuth } from "@/lib/auth";
import { useAudit, useDemoTargets } from "@/lib/queries";
import { btnPrimary, Empty, PageTitle, Panel, Pill, when } from "@/components/ui/bits";

type Slug = "replay-duplicate" | "stale-event" | "self-approval" | "double-approve";
type Outcome = DemoResult | { error: string };

const CONTROLS: { slug: Slug; title: string; what: string; expect: string; needs: "event" | "plan"; note?: string }[] = [
  { slug: "replay-duplicate", title: "Replay a duplicate webhook", needs: "event",
    what: "Sends the last carrier event again, byte for byte.",
    expect: "Acknowledged as a duplicate. Nothing changes." },
  { slug: "stale-event", title: "Send a stale event", needs: "event",
    what: "Sends an event with a sequence number the shipment has already passed.",
    expect: "Stored as stale and ignored. The shipment keeps its newer state." },
  { slug: "self-approval", title: "Attempt self-approval", needs: "plan",
    what: "Makes the person who proposed (or modified) the awaiting plan try to approve it.",
    expect: "Refused with 403, and the refusal is in the audit log under their name." },
  { slug: "double-approve", title: "Double approve (two tabs)", needs: "plan",
    what: "Approves the awaiting plan, then sends the same approval again with the old version, as a second tab would.",
    expect: "The first counts, the second gets 409.", note: "The first approval is real: the plan moves to Approved." },
];

const HOT = /^demo\.|blocked|denied|stale|duplicate|invalid|unauthorized/;

export default function DemoPage() {
  const { user } = useAuth();
  const ok = allowed(CAN.demoControls, user?.role);
  const qc = useQueryClient();
  const targets = useDemoTargets(ok);
  const audit = useAudit("", "", ok);
  const [out, setOut] = useState<Partial<Record<Slug, Outcome>>>({});

  const run = useMutation({
    mutationFn: (slug: Slug) => api<DemoResult>(`/demo/${slug}`, { method: "POST" }),
    onSuccess: (r, slug) => {
      setOut((o) => ({ ...o, [slug]: r }));
      if (r.guard_held) toast.success(r.headline); else toast.warning(r.headline);
      qc.invalidateQueries(); // the audit feed, the approvals queue and the badges all move
    },
    onError: (e, slug) => {
      const message = e instanceof Error ? e.message : "Failed";
      setOut((o) => ({ ...o, [slug]: { error: message } }));
      toast.error(message);
    },
  });

  if (!ok) return <><PageTitle title="Demo controls" /><Empty>Only the Administrator can use the demo controls.</Empty></>;
  const t = targets.data;

  return (
    <>
      <PageTitle title="Demo controls" sub="Fire each guard on purpose. The system does the refusing; the result shows up in the audit log below."
        actions={<Link href="/audit" className="text-xs font-medium text-brand">Open the audit log</Link>} />
      <div className="grid gap-4 md:grid-cols-2">
        {CONTROLS.map((c) => {
          const target = c.needs === "event" ? t?.last_event : t?.proposed_plan;
          const missing = !!t && !target;
          const o = out[c.slug];
          const pending = run.isPending && run.variables === c.slug;
          return (
            <Panel key={c.slug} title={c.title} aside={target ? `Target: ${target}` : missing ? (c.needs === "event" ? "No event yet" : "No plan awaiting approval") : undefined}>
              <p className="text-xs text-[#2f3944]">{c.what}</p>
              <p className="mt-1 text-[11px] text-[#5c6670]">Expected: {c.expect}</p>
              {c.note && <p className="mt-1 text-[11px] font-medium text-[#c77700]">{c.note}</p>}
              <button onClick={() => run.mutate(c.slug)} disabled={run.isPending || missing} className={`${btnPrimary} mt-3`}>
                {pending ? <Loader2 className="size-3.5 animate-spin" /> : <Play className="size-3.5" />} Run
              </button>
              {missing && <p className="mt-2 text-[11px] text-[#6b7480]">{c.needs === "event" ? "Fire a scenario first (python -m app.scenarios s1)." : "Propose a plan first, as the Operations Analyst."}</p>}
              {o && ("error" in o ? (
                <p role="alert" className="mt-3 rounded-lg bg-[#f8e4e1] px-3 py-2 text-xs text-[#8c2a22]">{o.error}</p>
              ) : (
                <div className={`mt-3 rounded-lg px-3 py-2 text-xs ${o.guard_held ? "bg-[#e3f0e7] text-[#1f5a3a]" : "bg-[#f8ecd3] text-[#8a5a00]"}`}>
                  <div className="flex items-center gap-1.5 font-semibold">
                    {o.guard_held ? <CheckCircle2 className="size-3.5" /> : <ShieldAlert className="size-3.5" />}{o.headline}
                  </div>
                  <ol className="mt-1.5 space-y-1">
                    {o.steps.map((s, i) => (
                      <li key={i} className="text-[11px] leading-snug">
                        <span className="font-semibold">{s.status_code} {s.outcome}</span>: {s.label}{s.detail ? ` (${s.detail})` : ""}
                      </li>))}
                  </ol>
                </div>
              ))}
            </Panel>
          );
        })}
      </div>

      <Panel title="Audit trail, live" aside="Newest first; updates as soon as a control finishes">
        {!audit.data?.length ? <p className="text-xs text-[#6b7480]">Nothing yet.</p> : (
          <table className="w-full text-left text-xs">
            <thead className="text-[10px] uppercase tracking-wide text-[#6b7480]"><tr>{["#", "Time", "Who", "Action", "Entity", "Reason"].map((h) => <th key={h} className="px-3 py-2 font-medium">{h}</th>)}</tr></thead>
            <tbody>{audit.data.slice(0, 12).map((r) => (
              <tr key={r.id} className="border-t border-[#ebe8e1]">
                <td className="px-3 py-2 text-[#6b7480]">{r.id}</td><td className="whitespace-nowrap px-3 py-2">{when(r.ts)}</td>
                <td className="px-3 py-2">{r.role ? ROLE_LABEL[r.role] ?? r.role : "System"}</td>
                <td className="px-3 py-2"><Pill tone={HOT.test(r.action) ? "bg-[#f8e4e1] text-[#c8352b]" : undefined}>{r.action}</Pill></td>
                <td className="px-3 py-2">{r.entity_type}{r.entity_id ? ` ${r.entity_id}` : ""}</td>
                <td className="max-w-xs truncate px-3 py-2 text-[#4a545e]">{r.reason ?? ""}</td>
              </tr>))}</tbody>
          </table>)}
      </Panel>
    </>
  );
}
