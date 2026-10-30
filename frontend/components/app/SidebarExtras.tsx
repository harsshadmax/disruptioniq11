"use client";

import Link from "next/link";
import { CheckCircle2, Keyboard, Loader2, Play } from "lucide-react";
import { allowed, CAN, type Disruption } from "@/lib/api/types";
import { useDisruptions } from "@/lib/queries";
import { inr } from "@/components/ui/bits";
import { Kbd, OPEN_SHORTCUTS_EVENT } from "./Shortcuts";
import { MAIN, OVERSIGHT, visibleNav } from "./nav";
import { useRunDetection } from "./useRunDetection";

const DOT: Record<string, string> = { high: "bg-[#c8352b]", medium: "bg-[#c77700]", low: "bg-[#2e7d4f]" };
const RANK: Record<string, number> = { high: 0, medium: 1, low: 2 };
const SHOWN = 3;

const label = "mb-1.5 px-1 text-[10px] font-semibold tracking-wider text-[#7d8791]";

function Tile({ href, value, text, tone }: { href: string; value: number | string; text: string; tone?: string }) {
  return (
    <Link href={href} className="rounded-xl border border-[#ddd9d0] bg-white px-3 py-2 transition hover:border-brand-edge hover:bg-brand-wash">
      <div className={`text-xl font-extrabold leading-none ${tone ?? "text-[#1b2430]"}`}>{value}</div>
      <div className="mt-1 text-[10px] leading-tight text-[#5c6670]">{text}</div>
    </Link>
  );
}

/** The sidebar's middle: live counts, what needs attention first, one action and the shortcut list. */
export function SidebarExtras({ role, waiting }: { role: string; waiting: number }) {
  const active = useDisruptions("active");
  const detect = useRunDetection();
  const list: Disruption[] = [...(active.data ?? [])]
    .sort((a, b) => (RANK[a.severity] ?? 3) - (RANK[b.severity] ?? 3) || b.penalty_exposure - a.penalty_exposure);
  const pages = visibleNav([...MAIN, ...OVERSIGHT], role);

  return (
    <div className="hidden flex-1 shrink-0 flex-col gap-4 lg:flex">
      <section aria-label="Today">
        <div className={label}>TODAY</div>
        <div className="grid grid-cols-2 gap-2">
          <Tile href="/disruptions" value={active.isLoading ? "…" : active.error ? "?" : list.length} text="Active disruptions"
            tone={list.length > 0 ? "text-[#c8352b]" : undefined} />
          <Tile href="/approvals" value={waiting} text="Waiting for you" tone={waiting > 0 ? "text-brand-ink" : undefined} />
        </div>
      </section>

      <section aria-label="Needs attention">
        <div className={label}>NEEDS ATTENTION</div>
        {active.error ? (
          <p className="px-1 text-[11px] text-[#6b7480]">Live status is unavailable right now.</p>
        ) : active.isLoading ? (
          <div className="h-16 animate-pulse rounded-xl bg-[#f1efe9]" aria-label="Loading disruptions" />
        ) : list.length === 0 ? (
          <p className="flex items-center gap-2 rounded-xl bg-[#e3f0e7] px-3 py-2 text-[11px] text-[#1f5a3a]">
            <CheckCircle2 className="size-4 shrink-0" /> All clear. No active disruptions.
          </p>
        ) : (
          <ul className="flex flex-col gap-1">
            {list.slice(0, SHOWN).map((d) => (
              <li key={d.id}>
                <Link href={`/disruptions/${d.id}`} className="flex items-start gap-2 rounded-lg px-2 py-1.5 hover:bg-[#f3f1ec]">
                  <span className={`mt-1.5 size-2 shrink-0 rounded-full ${DOT[d.severity] ?? "bg-[#6b7480]"}`} aria-label={`${d.severity} severity`} />
                  <span className="min-w-0 leading-tight">
                    <span className="block truncate text-xs font-semibold text-[#1b2430]">{d.warehouse} · {d.sku_code}</span>
                    <span className="block truncate text-[10px] text-[#5c6670]">{d.orders_at_risk} orders · {inr(d.penalty_exposure)} penalty</span>
                  </span>
                </Link>
              </li>
            ))}
            {list.length > SHOWN && (
              <li><Link href="/disruptions" className="block px-2 py-1 text-[11px] font-medium text-brand-ink hover:underline">See all {list.length}</Link></li>
            )}
          </ul>
        )}
        {allowed(CAN.runDetection, role) && (
          <button
            type="button" onClick={() => detect.mutate()} disabled={detect.isPending}
            title="Scan stock, orders and shipments for new disruptions"
            className="mt-2 flex h-8 w-full items-center justify-center gap-2 rounded-lg border border-brand-edge bg-brand-wash text-[11px] font-semibold text-brand-ink hover:bg-brand-soft disabled:opacity-50"
          >
            {detect.isPending ? <Loader2 className="size-3.5 animate-spin" /> : <Play className="size-3.5" />} Run detection now
          </button>
        )}
      </section>

      <section aria-label="Shortcuts" className="[@media(max-height:860px)]:hidden">
        <div className={label}>SHORTCUTS</div>
        <ul className="flex flex-col gap-1 px-1 text-[11px] text-[#4a545e]">
          <li className="flex items-center justify-between gap-1">Search <Kbd>/</Kbd></li>
          {pages.slice(0, 4).map((p) => (
            <li key={p.href} className="flex items-center justify-between gap-1">
              <span className="truncate">Go to {p.label}</span>
              <span className="flex shrink-0 gap-0.5"><Kbd>G</Kbd><Kbd>{p.key.toUpperCase()}</Kbd></span>
            </li>
          ))}
        </ul>
        <button
          type="button" onClick={() => window.dispatchEvent(new Event(OPEN_SHORTCUTS_EVENT))}
          className="mt-2 flex items-center gap-1.5 px-1 text-[11px] font-medium text-brand-ink hover:underline"
        >
          <Keyboard className="size-3.5" /> All shortcuts <Kbd>?</Kbd>
        </button>
      </section>
    </div>
  );
}
