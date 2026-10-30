"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { createContext, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Bell, CalendarDays, CheckCheck, Loader2, LogOut, Play, Search, Zap } from "lucide-react";
import { api } from "@/lib/api/client";
import { allowed, CAN, ROLE_LABEL } from "@/lib/api/types";
import { useAuth } from "@/lib/auth";
import { useInbox, usePlans } from "@/lib/queries";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { MAIN, OVERSIGHT, type NavItem } from "./nav";
import { Shortcuts } from "./Shortcuts";
import { SidebarExtras } from "./SidebarExtras";
import { useRunDetection } from "./useRunDetection";

type SearchState = { query: string; setQuery: (q: string) => void };
const SearchCtx = createContext<SearchState>({ query: "", setQuery: () => {} });
export const useSearch = () => useContext(SearchCtx);

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
    return <div className="flex min-h-screen items-center justify-center bg-[#e6e3dc] text-sm text-[#6b7480]">Loading…</div>;
  }
  return (
    <SearchCtx.Provider value={{ query, setQuery }}>
      <div className="min-h-screen bg-[#e6e3dc] p-3 md:p-6">
        <div className="mx-auto flex max-w-[1440px] overflow-clip rounded-2xl border border-[#d3cfc6] bg-white shadow-sm">
          <Shortcuts role={user.role} />
          <Sidebar user={user} onLogout={() => { logout(); router.replace("/login"); }} />
          <div className="flex min-w-0 flex-1 flex-col bg-[#f3f1ec]">
            <Topbar role={user.role} />
            <main className="flex flex-1 flex-col gap-4 p-4 md:p-5">
              {children}
              <footer className="mt-auto pt-2 text-center text-[11px] text-[#6b7480]">Synthetic demo data. No real customers, stock or money.</footer>
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
    items.filter((n) => !n.show || n.show(role)).map(({ href, icon: Icon, label, key }) => {
      const active = isActive(path, href);
      return (
        <Link
          key={href} href={href} title={`${label} (G then ${key.toUpperCase()})`} aria-label={label} aria-current={active ? "page" : undefined}
          className={`relative flex items-center justify-center gap-3 rounded-lg px-3 py-2 text-[13px] transition lg:justify-start ${
            active ? "bg-brand-soft font-semibold text-brand-ink" : "font-medium text-[#4a545e] hover:bg-[#f1efe9]"
          }`}
        >
          <Icon className="size-4 shrink-0" />
          <span className="hidden lg:inline">{label}</span>
          {href === "/approvals" && waiting > 0 && (
            <span className="absolute -right-0.5 -top-0.5 flex size-4 items-center justify-center rounded-full bg-[#1b2430] text-[9px] font-bold text-white lg:static lg:ml-auto lg:size-5 lg:text-[10px]">{waiting}</span>
          )}
        </Link>
      );
    });
  const oversight = renderNav(OVERSIGHT);

  return (
    <aside
      className="sticky top-0 flex h-[calc(100vh-1.5rem)] w-[68px] shrink-0 flex-col gap-4 self-start overflow-y-auto [scrollbar-width:thin] border-r border-[#ddd9d0] bg-white p-3 md:h-[calc(100vh-3rem)] lg:w-[240px] lg:p-4"
      aria-label="Sidebar"
    >
      <Link href="/" className="flex items-center gap-2.5 px-1">
        <span className="flex size-8 shrink-0 items-center justify-center rounded-lg bg-brand text-sm font-extrabold text-white">D</span>
        <span className="hidden text-[15px] font-bold tracking-tight text-[#1b2430] lg:inline">DisruptionIQ</span>
      </Link>

      <label className="hidden h-9 items-center gap-2 rounded-lg border border-[#ddd9d0] bg-white px-3 text-[#7d8791] focus-within:border-brand lg:flex">
        <Search className="size-3.5" />
        <input
          ref={searchRef} value={query} aria-label="Search disruptions"
          onChange={(e) => { setQuery(e.target.value); if (path !== "/" && path !== "/disruptions") router.push("/disruptions"); }}
          placeholder="Search…" className="w-full bg-transparent text-xs text-[#1b2430] outline-none placeholder:text-[#7d8791]"
        />
        <kbd className="rounded border border-[#ddd9d0] px-1.5 text-[10px] text-[#6b7480]">/</kbd>
      </label>

      <nav className="flex flex-col gap-1" aria-label="Main">
        <div className="mb-1 hidden px-2 text-[10px] font-semibold tracking-wider text-[#7d8791] lg:block">MAIN MENU</div>
        {renderNav(MAIN)}
        {oversight.length > 0 && (
          <>
            <div className="mb-1 mt-3 hidden px-2 text-[10px] font-semibold tracking-wider text-[#7d8791] lg:block">OVERSIGHT</div>
            {oversight}
          </>
        )}
      </nav>

      <SidebarExtras role={role} waiting={waiting} />

      <div className="mt-auto flex flex-col gap-3">
        <Link href="/approvals" className="hidden rounded-xl bg-brand-wash p-3 ring-1 ring-brand-edge lg:block [@media(max-height:800px)]:hidden!">
          <span className="flex size-8 items-center justify-center rounded-lg bg-brand text-white"><Zap className="size-4" /></span>
          <div className="mt-2 text-[13px] font-bold text-[#1b2430]">Your queue</div>
          <div className="text-[11px] leading-snug text-[#4a545e]">
            {waiting === 0 ? "Nothing waiting for your role." : `${toApprove} to approve, ${toExecute} to execute.`}
          </div>
          <div className="mt-2 rounded-lg border border-brand-edge bg-white px-3 py-1.5 text-center text-xs font-semibold text-brand-ink">Open approvals</div>
        </Link>
        <div className="flex items-center gap-2.5 border-t border-[#ddd9d0] pt-3">
          <span className="flex size-8 shrink-0 items-center justify-center rounded-full bg-brand-soft text-xs font-semibold text-brand-ink">{initialsOf(user.name)}</span>
          <div className="hidden min-w-0 flex-1 leading-tight lg:block">
            <div className="truncate text-[13px] font-semibold text-[#1b2430]">{user.name}</div>
            <div className="truncate text-[11px] text-[#6b7480]">{ROLE_LABEL[role] ?? role}</div>
          </div>
          <button onClick={onLogout} title="Sign out" aria-label="Sign out" className="hidden size-8 items-center justify-center rounded-lg text-[#6b7480] hover:bg-[#f1efe9] lg:flex">
            <LogOut className="size-4" />
          </button>
        </div>
        <button onClick={onLogout} title="Sign out" aria-label="Sign out" className="flex size-9 items-center justify-center self-center rounded-lg text-[#6b7480] hover:bg-[#f1efe9] lg:hidden">
          <LogOut className="size-4" />
        </button>
      </div>
    </aside>
  );
}

function RunDetection() {
  const detect = useRunDetection();
  return (
    <button
      onClick={() => detect.mutate()} disabled={detect.isPending} title="Scan stock, orders and shipments for new disruptions"
      className="flex h-9 items-center gap-2 rounded-lg bg-brand px-4 text-xs font-semibold text-white hover:bg-brand-deep disabled:opacity-50"
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
    <header className="flex h-14 shrink-0 items-center gap-3 border-b border-[#ddd9d0] bg-white px-4 md:px-5">
      <h1 className="mr-auto text-[15px] font-semibold text-[#1b2430]">{title}</h1>
      <span className="hidden h-9 items-center gap-2 rounded-lg border border-[#ddd9d0] px-3 text-xs font-medium text-[#2f3944] sm:flex" suppressHydrationWarning>
        <CalendarDays className="size-3.5 text-[#6b7480]" /> {today}
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
        className="relative flex size-9 items-center justify-center rounded-lg border border-[#ddd9d0] bg-white"
        title={`${unread} unread notifications`} aria-label={`Notifications, ${unread} unread`}
      >
        <Bell className="size-4 text-[#2f3944]" />
        {unread > 0 && (
          <span className="absolute -right-1 -top-1 flex min-w-4 items-center justify-center rounded-full border-2 border-white bg-[#c8352b] px-1 text-[9px] font-semibold text-white">{unread}</span>
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
          {(inbox.data?.items ?? []).length === 0 && <li className="px-4 py-8 text-center text-xs text-[#6b7480]">Nothing yet.</li>}
          {(inbox.data?.items ?? []).map((n) => (
            <li key={n.id}>
              <button onClick={() => open(n)} className={`flex w-full gap-3 px-4 py-3 text-left hover:bg-[#f3f1ec] ${n.read ? "" : "bg-brand-wash"}`}>
                <span className={`mt-1.5 size-2 shrink-0 rounded-full ${n.read ? "bg-transparent" : "bg-brand"}`} />
                <span className="min-w-0">
                  <span className="block text-xs leading-snug text-[#1b2430]">{n.message}</span>
                  <span className="mt-0.5 block text-[10px] text-[#6b7480]">{new Date(n.created_at).toLocaleString("en-GB", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" })}</span>
                </span>
              </button>
            </li>
          ))}
        </ul>
      </PopoverContent>
    </Popover>
  );
}
