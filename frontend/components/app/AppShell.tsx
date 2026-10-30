"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import {
  Bell, CheckCheck, ClipboardCheck, FlaskConical, LayoutDashboard, LogOut, Search, ScrollText, Truck, Upload,
} from "lucide-react";
import { api } from "@/lib/api/client";
import { allowed, CAN, ROLE_LABEL } from "@/lib/api/types";
import { useAuth } from "@/lib/auth";
import { useInbox, usePlans } from "@/lib/queries";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";

type SearchState = { query: string; setQuery: (q: string) => void };
const SearchCtx = createContext<SearchState>({ query: "", setQuery: () => {} });
export const useSearch = () => useContext(SearchCtx);

const NAV = [
  { href: "/", icon: LayoutDashboard, label: "Dashboard" },
  { href: "/disruptions", icon: Truck, label: "Disruptions" },
  { href: "/approvals", icon: ClipboardCheck, label: "Approvals" },
  { href: "/audit", icon: ScrollText, label: "Audit", show: (r?: string) => allowed(CAN.readAudit, r) },
  { href: "/import", icon: Upload, label: "Import" },
  { href: "/demo", icon: FlaskConical, label: "Demo controls", show: (r?: string) => allowed(CAN.demoControls, r) },
];

export function AppShell({ children }: { children: ReactNode }) {
  const { user, loading, logout } = useAuth();
  const router = useRouter();
  const [query, setQuery] = useState("");

  useEffect(() => {
    if (!loading && !user) router.replace("/login");
  }, [loading, user, router]);

  if (loading || !user) {
    return <div className="flex min-h-screen items-center justify-center bg-[#e6e6e9] text-sm text-[#8a8a8f]">Loading…</div>;
  }
  return (
    <SearchCtx.Provider value={{ query, setQuery }}>
      <div className="min-h-screen bg-[#e6e6e9] p-4 md:p-8">
        <div className="mx-auto flex max-w-[1320px] overflow-hidden rounded-[28px] bg-[#f6f6f7] shadow-xl shadow-black/5">
          <Sidebar role={user.role} />
          <main className="flex min-w-0 flex-1 flex-col gap-5 p-5">
            <Topbar name={user.name} role={user.role} onLogout={() => { logout(); router.replace("/login"); }} />
            {children}
            <footer className="mt-auto pt-2 text-center text-[11px] text-[#8a8a8f]">Synthetic demo data. No real customers, stock or money.</footer>
          </main>
        </div>
      </div>
    </SearchCtx.Provider>
  );
}

function Sidebar({ role }: { role: string }) {
  const path = usePathname();
  const mine = usePlans("PROPOSED");
  const ready = usePlans("APPROVED");
  const waiting = (mine.data ?? []).filter((p) => p.approver_roles.includes(role)).length
    + (ready.data ?? []).filter((p) => p.executor_roles.includes(role)).length;
  return (
    <aside className="flex w-[72px] shrink-0 flex-col items-center rounded-l-[28px] bg-white py-6">
      <Link href="/" className="mb-7 flex size-10 items-center justify-center rounded-full bg-[#e5384f] text-lg font-bold text-white">D</Link>
      <nav className="flex flex-col items-center gap-3" aria-label="Main">
        {NAV.filter((n) => !n.show || n.show(role)).map(({ href, icon: Icon, label }) => {
          const active = href === "/" ? path === "/" : path.startsWith(href);
          return (
            <Link
              key={href} href={href} title={label} aria-label={label} aria-current={active ? "page" : undefined}
              className={`relative flex size-11 items-center justify-center rounded-full transition ${
                active ? "bg-[#e5384f] text-white shadow-md shadow-[#e5384f]/30" : "text-[#9a9aa0] hover:bg-[#f3f3f5]"
              }`}
            >
              <Icon className="size-5" />
              {href === "/approvals" && waiting > 0 && (
                <span className="absolute -right-1 -top-1 flex min-w-4 items-center justify-center rounded-full border-2 border-white bg-[#f08a24] px-1 text-[9px] font-bold text-white">{waiting}</span>
              )}
            </Link>
          );
        })}
      </nav>
    </aside>
  );
}

function Topbar({ name, role, onLogout }: { name: string; role: string; onLogout: () => void }) {
  const { query, setQuery } = useSearch();
  const router = useRouter();
  const path = usePathname();
  const initials = name.split(" ").map((p) => p[0]).slice(0, 2).join("").toUpperCase();
  return (
    <header className="flex items-center gap-4">
      <label className="flex h-12 flex-1 items-center gap-3 rounded-2xl bg-white px-5 text-[#9a9aa0] shadow-sm">
        <Search className="size-4" />
        <input
          value={query} onChange={(e) => { setQuery(e.target.value); if (path !== "/" && path !== "/disruptions") router.push("/disruptions"); }}
          placeholder="Search by shipment, order, SKU or warehouse" aria-label="Search disruptions"
          className="w-full bg-transparent text-sm text-[#1c1c1e] outline-none placeholder:text-[#9a9aa0]"
        />
      </label>
      <Bell_ />
      <div className="flex h-12 items-center gap-3 rounded-2xl bg-white pl-2 pr-3 shadow-sm">
        <div className="flex size-9 items-center justify-center rounded-full bg-[#fdecee] text-sm font-semibold text-[#e5384f]">{initials}</div>
        <div className="leading-tight">
          <div className="text-sm font-semibold text-[#1c1c1e]">{name}</div>
          <div className="text-[11px] text-[#8a8a8f]">{ROLE_LABEL[role] ?? role}</div>
        </div>
        <button onClick={onLogout} title="Sign out" aria-label="Sign out" className="ml-1 flex size-8 items-center justify-center rounded-full text-[#8a8a8f] hover:bg-[#f3f3f5]">
          <LogOut className="size-4" />
        </button>
      </div>
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
        className="relative flex size-12 items-center justify-center rounded-2xl bg-white shadow-sm"
        title={`${unread} unread notifications`} aria-label={`Notifications, ${unread} unread`}
      >
        <Bell className="size-5 text-[#3a3a3f]" />
        {unread > 0 && (
          <span className="absolute -right-1 -top-1 flex min-w-5 items-center justify-center rounded-full border-2 border-white bg-[#e5384f] px-1 text-[10px] font-semibold text-white">{unread}</span>
        )}
      </PopoverTrigger>
      <PopoverContent align="end" className="w-96 gap-0 p-0">
        <div className="flex items-center justify-between border-b px-4 py-3">
          <div className="text-sm font-semibold">Notifications</div>
          <button disabled={unread === 0} onClick={() => readAll.mutate()} className="flex items-center gap-1 text-xs text-[#e5384f] disabled:opacity-40">
            <CheckCheck className="size-3.5" /> Mark all read
          </button>
        </div>
        <ul className="max-h-96 overflow-y-auto">
          {(inbox.data?.items ?? []).length === 0 && <li className="px-4 py-8 text-center text-xs text-[#8a8a8f]">Nothing yet.</li>}
          {(inbox.data?.items ?? []).map((n) => (
            <li key={n.id}>
              <button onClick={() => open(n)} className={`flex w-full gap-3 px-4 py-3 text-left hover:bg-[#f6f6f7] ${n.read ? "" : "bg-[#fff8f9]"}`}>
                <span className={`mt-1.5 size-2 shrink-0 rounded-full ${n.read ? "bg-transparent" : "bg-[#e5384f]"}`} />
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
