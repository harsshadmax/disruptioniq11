"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { createContext, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import {
  Bell, CalendarDays, CheckCheck, ClipboardCheck, FlaskConical, LayoutDashboard, Loader2, LogOut, Play, Search,
  ScrollText, Truck, Upload, Zap,
} from "lucide-react";
import { toast } from "sonner";
import { runDetection } from "@/lib/api";
import { api } from "@/lib/api/client";
import { allowed, CAN, ROLE_LABEL } from "@/lib/api/types";
import { useAuth } from "@/lib/auth";
import { useInbox, usePlans } from "@/lib/queries";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";

type SearchState = { query: string; setQuery: (q: string) => void };
const SearchCtx = createContext<SearchState>({ query: "", setQuery: () => {} });
export const useSearch = () => useContext(SearchCtx);

type NavItem = { href: string; icon: typeof Truck; label: string; show?: (r?: string) => boolean };
const MAIN: NavItem[] = [
  { href: "/", icon: LayoutDashboard, label: "Dashboard" },
  { href: "/disruptions", icon: Truck, label: "Disruptions" },
  { href: "/approvals", icon: ClipboardCheck, label: "Approvals" },
  { href: "/import", icon: Upload, label: "Import" },
];
const OVERSIGHT: NavItem[] = [
  { href: "/audit", icon: ScrollText, label: "Audit", show: (r) => allowed(CAN.readAudit, r) },
  { href: "/demo", icon: FlaskConical, label: "Demo controls", show: (r) => allowed(CAN.demoControls, r) },
];

const initialsOf = (name: string) => name.split(" ").map((p) => p[0]).slice(0, 2).join("").toUpperCase();
const isActive = (path: string, href: string) => (href === "/" ? path === "/" : path.startsWith(href));

export function AppShell({ children }: { children: ReactNode }) {
  const { user, loading, logout } = useAuth();
  const router = useRouter();
  const [query, setQuery] = useState("");

  useEffect(() => {
    if (!loading && !user) router.replace("/login");
  }, [loading, user, router]);

  if (loading || !user) {
    return <div className="flex min-h-screen items-center justify-center bg-[#e9e6f4] text-sm text-[#8a8a8f]">Loading…</div>;
  }
  return (
    <SearchCtx.Provider value={{ query, setQuery }}>
      <div className="min-h-screen bg-[#e9e6f4] p-3 md:p-6">
        <div className="mx-auto flex max-w-[1440px] overflow-hidden rounded-[22px] border border-[#dfe2e4] bg-white shadow-xl shadow-black/5">
          <Sidebar user={user} onLogout={() => { logout(); router.replace("/login"); }} />
          <div className="flex min-w-0 flex-1 flex-col bg-[#f6f4fc]">
            <Topbar role={user.role} />
            <main className="flex flex-1 flex-col gap-4 p-4 md:p-5">
              {children}
              <footer className="mt-auto pt-2 text-center text-[11px] text-[#8a8a8f]">Synthetic demo data. No real customers, stock or money.</footer>
            </main>
          </div>
        </div>
      </div>
    </SearchCtx.Provider>
  );
}

function Sidebar({ user, onLogout }: { user: { name: string; role: string }; onLogout: () => void }) {
  const path = usePathname();
  const router = useRouter();
  const { query, setQuery } = useSearch();
  const searchRef = useRef<HTMLInputElement>(null);
  const role = user.role;
  const proposed = usePlans("PROPOSED");
  const approved = usePlans("APPROVED");
  const toApprove = (proposed.data ?? []).filter((p) => p.approver_roles.includes(role)).length;
  const toExecute = (approved.data ?? []).filter((p) => p.executor_roles.includes(role)).length;
  const waiting = toApprove + toExecute;

  useEffect(() => {  // "/" jumps to the search box, like the template's shortcut
    const onKey = (e: KeyboardEvent) => {
      const el = e.target as HTMLElement | null;
      if (e.key === "/" && !(el && (el.tagName === "INPUT" || el.tagName === "TEXTAREA" || el.isContentEditable))) {
        e.preventDefault();
        searchRef.current?.focus();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const renderNav = (items: NavItem[]) =>
    items.filter((n) => !n.show || n.show(role)).map(({ href, icon: Icon, label }) => {
      const active = isActive(path, href);
      return (
        <Link
          key={href} href={href} title={label} aria-label={label} aria-current={active ? "page" : undefined}
          className={`relative flex items-center justify-center gap-3 rounded-lg px-3 py-2 text-[13px] transition lg:justify-start ${
            active ? "bg-brand-soft font-semibold text-brand-ink" : "font-medium text-[#55555a] hover:bg-[#f3f5f4]"
          }`}
        >
          <Icon className="size-4 shrink-0" />
          <span className="hidden lg:inline">{label}</span>
          {href === "/approvals" && waiting > 0 && (
            <span className="absolute -right-0.5 -top-0.5 flex size-4 items-center justify-center rounded-full bg-[#1c1c1e] text-[9px] font-bold text-white lg:static lg:ml-auto lg:size-5 lg:text-[10px]">{waiting}</span>
          )}
        </Link>
      );
    });
  const oversight = renderNav(OVERSIGHT);

  return (
    <aside className="flex w-[68px] shrink-0 flex-col gap-4 border-r border-[#e6e8ec] bg-white p-3 lg:w-[240px] lg:p-4" aria-label="Sidebar">
      <Link href="/" className="flex items-center gap-2.5 px-1">
        <span className="flex size-8 shrink-0 items-center justify-center rounded-lg bg-brand text-sm font-extrabold text-white">D</span>
        <span className="hidden text-[15px] font-bold tracking-tight text-[#1c1c1e] lg:inline">DisruptionIQ</span>
      </Link>

      <label className="hidden h-9 items-center gap-2 rounded-lg border border-[#e6e8ec] bg-white px-3 text-[#9a9aa0] focus-within:border-brand lg:flex">
        <Search className="size-3.5" />
        <input
          ref={searchRef} value={query} aria-label="Search disruptions"
          onChange={(e) => { setQuery(e.target.value); if (path !== "/" && path !== "/disruptions") router.push("/disruptions"); }}
          placeholder="Search…" className="w-full bg-transparent text-xs text-[#1c1c1e] outline-none placeholder:text-[#9a9aa0]"
        />
        <kbd className="rounded border border-[#e6e8ec] px-1.5 text-[10px] text-[#8a8a8f]">/</kbd>
      </label>

      <nav className="flex flex-col gap-1" aria-label="Main">
        <div className="mb-1 hidden px-2 text-[10px] font-semibold tracking-wider text-[#9a9aa0] lg:block">MAIN MENU</div>
        {renderNav(MAIN)}
        {oversight.length > 0 && (
          <>
            <div className="mb-1 mt-3 hidden px-2 text-[10px] font-semibold tracking-wider text-[#9a9aa0] lg:block">OVERSIGHT</div>
            {oversight}
          </>
        )}
      </nav>

      <div className="mt-auto flex flex-col gap-3">
        <Link href="/approvals" className="hidden rounded-xl bg-gradient-to-br from-[#e3dcfb] via-[#efeafd] to-[#f8f6ff] p-3 ring-1 ring-brand-edge lg:block">
          <span className="flex size-8 items-center justify-center rounded-lg bg-brand text-white"><Zap className="size-4" /></span>
          <div className="mt-2 text-[13px] font-bold text-[#1c1c1e]">Your queue</div>
          <div className="text-[11px] leading-snug text-[#55555a]">
            {waiting === 0 ? "Nothing waiting for your role." : `${toApprove} to approve, ${toExecute} to execute.`}
          </div>
          <div className="mt-2 rounded-lg border border-brand-edge bg-white px-3 py-1.5 text-center text-xs font-semibold text-brand-ink">Open approvals</div>
        </Link>
        <div className="flex items-center gap-2.5 border-t border-[#e6e8ec] pt-3">
          <span className="flex size-8 shrink-0 items-center justify-center rounded-full bg-brand-soft text-xs font-semibold text-brand-ink">{initialsOf(user.name)}</span>
          <div className="hidden min-w-0 flex-1 leading-tight lg:block">
            <div className="truncate text-[13px] font-semibold text-[#1c1c1e]">{user.name}</div>
            <div className="truncate text-[11px] text-[#8a8a8f]">{ROLE_LABEL[role] ?? role}</div>
          </div>
          <button onClick={onLogout} title="Sign out" aria-label="Sign out" className="hidden size-8 items-center justify-center rounded-lg text-[#8a8a8f] hover:bg-[#f3f5f4] lg:flex">
            <LogOut className="size-4" />
          </button>
        </div>
        <button onClick={onLogout} title="Sign out" aria-label="Sign out" className="flex size-9 items-center justify-center self-center rounded-lg text-[#8a8a8f] hover:bg-[#f3f5f4] lg:hidden">
          <LogOut className="size-4" />
        </button>
      </div>
    </aside>
  );
}

function RunDetection() {
  const qc = useQueryClient();
  const detect = useMutation({
    mutationFn: runDetection,
    onSuccess: (r) => {
      toast.success(`Detection finished: ${r.created.length} new, ${r.updated.length} updated, ${r.resolved.length} resolved.`);
      qc.invalidateQueries();
    },
    onError: (e) => toast.error(e instanceof Error ? e.message : "Detection failed"),
  });
  return (
    <button
      onClick={() => detect.mutate()} disabled={detect.isPending} title="Scan stock, orders and shipments for new disruptions"
      className="flex h-9 items-center gap-2 rounded-lg bg-brand px-4 text-xs font-semibold text-white shadow-sm shadow-brand/30 hover:bg-brand-deep disabled:opacity-50"
    >
      {detect.isPending ? <Loader2 className="size-3.5 animate-spin" /> : <Play className="size-3.5" />} Run detection
    </button>
  );
}

function Topbar({ role }: { role: string }) {
  const path = usePathname();
  const title = [...MAIN, ...OVERSIGHT].find((n) => isActive(path, n.href))?.label ?? "DisruptionIQ";
  const today = new Date().toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" });
  return (
    <header className="flex h-14 shrink-0 items-center gap-3 border-b border-[#e6e8ec] bg-white px-4 md:px-5">
      <h1 className="mr-auto text-[15px] font-semibold text-[#1c1c1e]">{title}</h1>
      <span className="hidden h-9 items-center gap-2 rounded-lg border border-[#e6e8ec] px-3 text-xs font-medium text-[#3a3a3f] sm:flex" suppressHydrationWarning>
        <CalendarDays className="size-3.5 text-[#8a8a8f]" /> {today}
      </span>
      <Bell_ />
      {allowed(CAN.runDetection, role) && <RunDetection />}
    </header>
  );
}

function Bell_() {
  const inbox = useInbox();
  const qc = useQueryClient();
  const router = useRouter();
  const refresh = () => qc.invalidateQueries({ queryKey: ["inbox"] });
  const read = useMutation({ mutationFn: (id: number) => api(`/notifications/${id}/read`, { method: "POST" }), onSuccess: refresh });
  const readAll = useMutation({ mutationFn: () => api("/notifications/read-all", { method: "POST" }), onSuccess: refresh });
  const unread = inbox.data?.unread ?? 0;

  function open(n: { id: number; read: boolean; entity_ref: string | null }) {
    if (!n.read) read.mutate(n.id);
    const ref = n.entity_ref ?? "";
    if (ref.startsWith("plan:")) router.push("/approvals");
    else if (ref.startsWith("disruption:")) router.push(`/disruptions/${ref.split(":")[1]}`);
  }

  return (
    <Popover>
      <PopoverTrigger
        className="relative flex size-9 items-center justify-center rounded-lg border border-[#e6e8ec] bg-white"
        title={`${unread} unread notifications`} aria-label={`Notifications, ${unread} unread`}
      >
        <Bell className="size-4 text-[#3a3a3f]" />
        {unread > 0 && (
          <span className="absolute -right-1 -top-1 flex min-w-4 items-center justify-center rounded-full border-2 border-white bg-[#e5384f] px-1 text-[9px] font-semibold text-white">{unread}</span>
        )}
      </PopoverTrigger>
      <PopoverContent align="end" className="w-96 gap-0 p-0">
        <div className="flex items-center justify-between border-b px-4 py-3">
          <div className="text-sm font-semibold">Notifications</div>
          <button disabled={unread === 0} onClick={() => readAll.mutate()} className="flex items-center gap-1 text-xs text-brand disabled:opacity-40">
            <CheckCheck className="size-3.5" /> Mark all read
          </button>
        </div>
        <ul className="max-h-96 overflow-y-auto">
          {(inbox.data?.items ?? []).length === 0 && <li className="px-4 py-8 text-center text-xs text-[#8a8a8f]">Nothing yet.</li>}
          {(inbox.data?.items ?? []).map((n) => (
            <li key={n.id}>
              <button onClick={() => open(n)} className={`flex w-full gap-3 px-4 py-3 text-left hover:bg-[#f6f4fc] ${n.read ? "" : "bg-brand-wash"}`}>
                <span className={`mt-1.5 size-2 shrink-0 rounded-full ${n.read ? "bg-transparent" : "bg-brand"}`} />
                <span className="min-w-0">
                  <span className="block text-xs leading-snug text-[#1c1c1e]">{n.message}</span>
                  <span className="mt-0.5 block text-[10px] text-[#8a8a8f]">{new Date(n.created_at).toLocaleString("en-GB", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" })}</span>
                </span>
              </button>
            </li>
          ))}
        </ul>
      </PopoverContent>
    </Popover>
  );
}
