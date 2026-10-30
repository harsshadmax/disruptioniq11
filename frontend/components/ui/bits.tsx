import type { ReactNode } from "react";

/** Small shared presentation helpers for the console pages. */
export const BAND_TONE: Record<string, string> = {
  high: "bg-[#f8e4e1] text-[#c8352b]",
  medium: "bg-[#f8ecd3] text-[#c77700]",
  low: "bg-[#e3f0e7] text-[#2e7d4f]",
};
export const STATUS_TONE: Record<string, string> = {
  DRAFT: "bg-[#ece9e2] text-[#555]",
  PROPOSED: "bg-[#f8ecd3] text-[#c77700]",
  APPROVED: "bg-[#e3ecff] text-[#3b6fe0]",
  EXECUTING: "bg-[#e3ecff] text-[#3b6fe0]",
  COMPLETED: "bg-[#e3f0e7] text-[#2e7d4f]",
  REJECTED: "bg-[#f8e4e1] text-[#c8352b]",
  STALE: "bg-[#f8e4e1] text-[#c8352b]",
};

export function Pill({ tone, children }: { tone?: string; children: ReactNode }) {
  return <span className={`inline-block rounded-md px-2 py-0.5 text-[10px] font-semibold capitalize ${tone ?? "bg-[#ece9e2] text-[#555]"}`}>{children}</span>;
}

export function Panel({ title, aside, children, className = "" }: { title?: string; aside?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <section className={`rounded-2xl bg-white p-4 shadow-sm ${className}`}>
      {(title || aside) && (
        <div className="mb-3 flex items-baseline justify-between gap-3">
          {title && <h2 className="text-sm font-bold text-[#1b2430]">{title}</h2>}
          {aside && <div className="text-[11px] text-[#6b7480]">{aside}</div>}
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
        <h1 className="text-[26px] font-extrabold leading-tight tracking-tight text-[#1b2430]">{title}</h1>
        {sub && <div className="mt-1 text-xs text-[#5c6670]">{sub}</div>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="rounded-2xl bg-white p-8 text-center text-sm text-[#5c6670] shadow-sm">{children}</div>;
}

export function ErrorBox({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  return (
    <div role="alert" className="rounded-2xl bg-white p-5 text-sm shadow-sm">
      <div className="font-semibold text-[#8c2a22]">Something went wrong</div>
      <div className="mt-1 text-[#5c6670]">{error instanceof Error ? error.message : "Unknown error"}</div>
      {onRetry && <button onClick={onRetry} className="mt-3 rounded-lg bg-brand px-4 py-2 text-xs font-semibold text-white">Retry</button>}
    </div>
  );
}

export const btnPrimary = "flex items-center gap-2 rounded-lg bg-brand px-4 py-2 text-xs font-semibold text-white disabled:opacity-50";
export const btnOutline = "flex items-center gap-2 rounded-lg border border-[#cfcac0] bg-white px-4 py-2 text-xs font-medium text-[#1b2430] disabled:opacity-40";

export const inr = (n: number) => `₹${Math.round(n).toLocaleString("en-IN")}`;
export const when = (iso: string) => new Date(iso).toLocaleString("en-GB", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
export const dayOf = (iso: string | null | undefined) => (iso ? new Date(iso).toLocaleDateString("en-GB", { day: "numeric", month: "short" }) : "n/a");
