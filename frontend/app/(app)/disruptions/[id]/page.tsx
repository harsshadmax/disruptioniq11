"use client";

import Link from "next/link";
import { useParams, useSearchParams } from "next/navigation";
import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ArrowRight, Loader2, MessageSquareText, PenLine } from "lucide-react";
import { api } from "@/lib/api/client";
import { allowed, CAN, type AiText, type RankedOrder } from "@/lib/api/types";
import { useAuth } from "@/lib/auth";
import { useDisruption, useOrders } from "@/lib/queries";
import { BAND_TONE, btnOutline, btnPrimary, dayOf, Empty, ErrorBox, inr, PageTitle, Panel, Pill } from "@/components/ui/bits";
import { RippleGraph } from "@/components/ripple/RippleGraph";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet";

const TYPE: Record<string, string> = { late_shipment: "Late shipment", supplier_delay: "Supplier delay", stock_shortage: "Stock shortage" };
const COVER: Record<string, string> = { full: "bg-[#e3f0e7] text-[#2e7d4f]", partial: "bg-[#f8ecd3] text-[#c77700]", none: "bg-[#f8e4e1] text-[#c8352b]" };

export default function DisruptionPage() {
  const id = Number(useParams<{ id: string }>().id);
  const { user } = useAuth();
  const qc = useQueryClient();
  const d = useDisruption(id);
  const orders = useOrders(id);
  const [picked, setPicked] = useState<RankedOrder | null>(null);
  const [closed, setClosed] = useState(false);
  // A link such as /disruptions/3?order=17 (from the dashboard's ripple map) opens that order's panel on arrival.
  const linked = Number(useSearchParams().get("order"));
  const why = picked ?? (closed ? null : orders.data?.find((o) => o.order_id === linked) ?? null);
  const setWhy = (o: RankedOrder | null) => { setPicked(o); if (!o) setClosed(true); };
  const canAi = allowed(CAN.useAi, user?.role);

  const rewrite = useMutation({
    mutationFn: () => api<AiText>(`/ai/disruptions/${id}/summary`, { method: "POST" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["disruption", id] }),
  });

  if (d.error) return <ErrorBox error={d.error} onRetry={() => d.refetch()} />;
  if (!d.data) return <div className="h-96 animate-pulse rounded-2xl bg-white" />;
  const x = d.data;
  const lines = x.impact.lines;

  return (
    <>
      <PageTitle
        title={`DIS-${x.id}: ${x.shipment_ref ? `${TYPE[x.type] ?? x.type} ${x.shipment_ref}` : `${x.sku_code} at ${x.warehouse}`}`}
        sub={<span className="flex flex-wrap items-center gap-2"><Pill tone={BAND_TONE[x.severity]}>{x.severity} risk</Pill>
          <span>{x.warehouse} · {x.sku_code} {x.sku_name}</span>{x.supplier && <span>· {x.supplier}</span>}
          {x.promised_eta && x.current_eta && <span>· ETA {dayOf(x.promised_eta)} <ArrowRight className="inline size-3" /> {dayOf(x.current_eta)}</span>}
          {x.status !== "active" && <Pill>{x.status}</Pill>}</span>}
        actions={<Link href={`/disruptions/${x.id}/plans`} className={btnPrimary}>Compare recovery plans <ArrowRight className="size-3.5" /></Link>}
      />

      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_320px]">
        <Panel title="Summary" aside={canAi && (
          <button onClick={() => rewrite.mutate()} disabled={rewrite.isPending} className="flex items-center gap-1 text-brand disabled:opacity-50">
            {rewrite.isPending ? <Loader2 className="size-3 animate-spin" /> : <PenLine className="size-3" />} Rewrite with AI
          </button>)}>
          <p className="text-sm leading-relaxed text-[#2f3944]">{x.summary}</p>
          {rewrite.data && <p className="mt-2 text-[10px] text-[#6b7480]">{rewrite.data.source === "ai" ? "Written by AI; every number was checked against the data." : `Template text (${rewrite.data.fallback_reason ?? "AI off"}).`}</p>}
          {rewrite.error && <p role="alert" className="mt-2 text-xs text-[#c8352b]">{(rewrite.error as Error).message}</p>}
        </Panel>
        <Panel title="At a glance">
          <dl className="grid grid-cols-3 gap-2 text-center">
            {[["At risk", x.orders_at_risk], ["Newly at risk", x.newly_at_risk], ["Penalty", inr(x.penalty_exposure)]].map(([k, v]) => (
              <div key={k as string} className="rounded-xl bg-[#f3f1ec] p-2"><dt className="text-[10px] text-[#6b7480]">{k}</dt><dd className="text-base font-bold">{v}</dd></div>
            ))}
          </dl>
          <p className="mt-3 text-[11px] text-[#5c6670]">Fully covered orders: <b>{x.impact.covered_before}</b> promised, <b>{x.impact.covered_after}</b> now.</p>
        </Panel>
      </div>

      <Panel title="Ripple map" aside="From the delayed shipment to the customers waiting on it">
        {orders.data ? <RippleGraph d={x} orders={orders.data} onSelectOrder={setWhy} />
          : <div className="h-64 animate-pulse rounded-xl bg-[#f3f1ec]" />}
      </Panel>

      <Panel title="Before vs after" aside="Promised plan against the current world, earliest due date served first">
        {lines.length === 0 ? <p className="text-xs text-[#6b7480]">No open orders for this SKU at this warehouse.</p> : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs">
              <thead className="text-[10px] uppercase tracking-wide text-[#6b7480]"><tr>
                {["Order", "Customer", "Due", "Qty", "Promised", "Now", "Covered"].map((h) => <th key={h} className="px-3 py-2 font-medium">{h}</th>)}</tr></thead>
              <tbody>{lines.map((l) => (
                <tr key={l.order_ref} className="border-t border-[#ebe8e1]">
                  <td className="px-3 py-2 font-semibold">{l.order_ref}{l.newly_at_risk && <span className="ml-2 text-[10px] text-[#c8352b]">newly at risk</span>}</td>
                  <td className="px-3 py-2">{l.customer} <span className="text-[10px] text-[#6b7480]">{l.tier}</span></td>
                  <td className="px-3 py-2">{dayOf(l.due_date)}</td><td className="px-3 py-2">{l.qty}</td>
                  <td className="px-3 py-2"><Pill tone={COVER[l.before]}>{l.before}</Pill></td>
                  <td className="px-3 py-2"><Pill tone={COVER[l.after]}>{l.after}</Pill></td>
                  <td className="px-3 py-2">{l.covered_after} of {l.qty}</td>
                </tr>))}</tbody>
            </table>
          </div>)}
      </Panel>

      <Panel title="Ranked orders at risk" aside="Score = weighted factors, higher is worse">
        {orders.isLoading && <div className="h-32 animate-pulse rounded-xl bg-[#f3f1ec]" />}
        {orders.data?.length === 0 && <p className="text-xs text-[#6b7480]">No order is at risk.</p>}
        {!!orders.data?.length && (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs">
              <thead className="text-[10px] uppercase tracking-wide text-[#6b7480]"><tr>
                {["#", "Order", "Customer", "Due", "Short", "Penalty", "Score", ""].map((h) => <th key={h} className="px-3 py-2 font-medium">{h}</th>)}</tr></thead>
              <tbody>{orders.data.map((o) => (
                <tr key={o.order_id} className="border-t border-[#ebe8e1]">
                  <td className="px-3 py-2 text-[#6b7480]">{o.rank}</td>
                  <td className="px-3 py-2 font-semibold">{o.order_ref}{o.newly_at_risk && <span className="ml-2 text-[10px] text-[#c8352b]">new</span>}</td>
                  <td className="px-3 py-2">{o.customer} <span className="text-[10px] text-[#6b7480]">{o.tier}</span></td>
                  <td className="px-3 py-2">{dayOf(o.due_date)}</td><td className="px-3 py-2">{o.uncovered_qty} of {o.order_qty}</td>
                  <td className="px-3 py-2">{inr(o.sla_penalty)}</td>
                  <td className="px-3 py-2"><Pill tone={BAND_TONE[o.band]}>{o.score.toFixed(1)} {o.band}</Pill></td>
                  <td className="px-3 py-2 text-right"><button onClick={() => setWhy(o)} className={btnOutline}>Why?</button></td>
                </tr>))}</tbody>
            </table>
          </div>)}
      </Panel>
      {!orders.data && !orders.isLoading && <Empty>Could not load the orders.</Empty>}

      <WhyDrawer order={why} disruptionId={id} canAi={canAi} onClose={() => setWhy(null)} />
    </>
  );
}

function WhyDrawer({ order, disruptionId, canAi, onClose }: { order: RankedOrder | null; disruptionId: number; canAi: boolean; onClose: () => void }) {
  const explain = useMutation({
    mutationFn: (orderId: number) => api<AiText>(`/ai/disruptions/${disruptionId}/orders/${orderId}/explain`, { method: "POST" }),
  });
  return (
    <Sheet open={!!order} onOpenChange={(o) => { if (!o) { explain.reset(); onClose(); } }}>
      <SheetContent side="right" className="overflow-y-auto sm:max-w-md">
        {order && (
          <>
            <SheetHeader>
              <SheetTitle>Why is {order.order_ref} ranked #{order.rank}?</SheetTitle>
              <SheetDescription>{order.customer} · {order.tier} · due {dayOf(order.due_date)} · score {order.score.toFixed(1)} ({order.band})</SheetDescription>
            </SheetHeader>
            <div className="space-y-4 px-4 pb-6">
              {order.factors.map((f) => (
                <div key={f.name}>
                  <div className="flex items-baseline justify-between text-xs"><span className="font-semibold capitalize">{f.name}</span><span className="text-[#5c6670]">{f.points.toFixed(1)} of {(f.weight * 100).toFixed(0)} points</span></div>
                  <div className="mt-1 h-2 overflow-hidden rounded-full bg-[#ece9e2]" role="img" aria-label={`${f.name}: ${f.points.toFixed(1)} of ${(f.weight * 100).toFixed(0)}`}>
                    <div className="h-full rounded-full bg-[#c8352b]" style={{ width: `${f.weight ? Math.min(100, (f.points / (f.weight * 100)) * 100) : 0}%` }} />
                  </div>
                  <p className="mt-1 text-[11px] text-[#5c6670]">{f.text}</p>
                </div>
              ))}
              <dl className="grid grid-cols-2 gap-2 rounded-xl bg-[#f3f1ec] p-3 text-xs">
                <div><dt className="text-[10px] text-[#6b7480]">Covered before</dt><dd className="font-semibold">{order.status_before}</dd></div>
                <div><dt className="text-[10px] text-[#6b7480]">Covered now</dt><dd className="font-semibold">{order.status_after}</dd></div>
                <div><dt className="text-[10px] text-[#6b7480]">Earliest fulfilment</dt><dd className="font-semibold">{order.earliest_fulfil ? dayOf(order.earliest_fulfil) : "none in sight"}</dd></div>
                <div><dt className="text-[10px] text-[#6b7480]">SLA penalty</dt><dd className="font-semibold">{inr(order.sla_penalty)}</dd></div>
              </dl>
              {canAi && (
                <div>
                  <button onClick={() => explain.mutate(order.order_id)} disabled={explain.isPending} className={btnPrimary}>
                    {explain.isPending ? <Loader2 className="size-3.5 animate-spin" /> : <MessageSquareText className="size-3.5" />} Explain in words
                  </button>
                  {explain.data && (<><p className="mt-3 text-sm leading-relaxed">{explain.data.text}</p>
                    <p className="mt-1 text-[10px] text-[#6b7480]">{explain.data.source === "ai" ? "AI-written, numbers checked against the data." : "Template text built from the factors above."}</p></>)}
                  {explain.error && <p role="alert" className="mt-2 text-xs text-[#c8352b]">{(explain.error as Error).message}</p>}
                </div>
              )}
            </div>
          </>
        )}
      </SheetContent>
    </Sheet>
  );
}
