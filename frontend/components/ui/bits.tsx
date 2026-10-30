import type { ReactNode } from "react";

/** Small shared presentation helpers for the console pages. */
export const BAND_TONE: Record<string, string> = {
  high: "bg-[#fdecee] text-[#e5384f]",
  medium: "bg-[#fff1e3] text-[#d9741a]",
  low: "bg-[#e6f6ea] text-[#16a34a]",
};
export const STATUS_TONE: Record<string, string> = {
  DRAFT: "bg-[#eef0f3] text-[#555]",
  PROPOSED: "bg-[#fff1e3] text-[#d9741a]",
  APPROVED: "bg-[#e3ecff] text-[#3b6fe0]",
  EXECUTING: "bg-[#e3ecff] text-[#3b6fe0]",
  COMPLETED: "bg-[#e6f6ea] text-[#16a34a]",
  REJECTED: "bg-[#fdecee] text-[#e5384f]",
  STALE: "bg-[#fdecee] text-[#e5384f]",
};

export function Pill({ tone, children }: { tone?: string; children: ReactNode }) {
  return <span className={`inline-block rounded-md px-2 py-0.5 text-[10px] font-semibold capitalize ${tone ?? "bg-[#eef0f3] text-[#555]"}`}>{children}</span>;
}

export function Panel({ title, aside, children, className = "" }: { title?: string; aside?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <section className={`rounded-2xl bg-white p-4 shadow-sm ${className}`}>
      {(title || aside) && (
        <div className="mb-3 flex items-baseline justify-between gap-3">
          {title && <h2 className="text-sm font-bold text-[#1c1c1e]">{title}</h2>}
          {aside && <div className="text-[11px] text-[#8a8a8f]">{aside}</div>}
        </div>
      )}
      {children}
    </section>
  );
}

export function PageTitle({ title, sub, actions }: { title: string; sub?: ReactNode; actions?: ReactNode }) {
  return (
    <div className="flex flex-wrap items-end justify-between gap-3">
      <div>
        <h1 className="text-[26px] font-extrabold leading-tight tracking-tight text-[#1c1c1e]">{title}</h1>
        {sub && <div className="mt-1 text-xs text-[#6b6b70]">{sub}</div>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="rounded-2xl bg-white p-8 text-center text-sm text-[#6b6b70] shadow-sm">{children}</div>;
}

export function ErrorBox({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  return (
    <div role="alert" className="rounded-2xl bg-white p-5 text-sm shadow-sm">
      <div className="font-semibold text-[#9b1c2e]">Something went wrong</div>
      <div className="mt-1 text-[#6b6b70]">{error instanceof Error ? error.message : "Unknown error"}</div>
      {onRetry && <button onClick={onRetry} className="mt-3 rounded-full bg-[#e5384f] px-4 py-2 text-xs font-semibold text-white">Retry</button>}
    </div>
  );
}

export const btnPrimary = "flex items-center gap-2 rounded-full bg-[#e5384f] px-4 py-2 text-xs font-semibold text-white shadow-md shadow-[#e5384f]/25 disabled:opacity-50";
export const btnOutline = "flex items-center gap-2 rounded-full border border-[#d9d9de] bg-white px-4 py-2 text-xs font-medium text-[#1c1c1e] disabled:opacity-40";

export const inr = (n: number) => `₹${Math.round(n).toLocaleString("en-IN")}`;
export const when = (iso: string) => new Date(iso).toLocaleString("en-GB", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
export const dayOf = (iso: string | null | undefined) => (iso ? new Date(iso).toLocaleDateString("en-GB", { day: "numeric", month: "short" }) : "n/a");
