import {
  ClipboardCheck, FlaskConical, LayoutDashboard, ScrollText, SlidersHorizontal, Truck, Upload,
} from "lucide-react";
import { allowed, CAN } from "@/lib/api/types";

/** `key` is the letter pressed after "G" to jump to the page (see Shortcuts.tsx). */
export type NavItem = { href: string; icon: typeof Truck; label: string; key: string; show?: (r?: string) => boolean };

export const MAIN: NavItem[] = [
  { href: "/", icon: LayoutDashboard, label: "Dashboard", key: "d" },
  { href: "/disruptions", icon: Truck, label: "Disruptions", key: "s" },
  { href: "/approvals", icon: ClipboardCheck, label: "Approvals", key: "a" },
  { href: "/simulate", icon: SlidersHorizontal, label: "What-if lab", key: "w", show: (r) => allowed(CAN.simulate, r) },
  { href: "/import", icon: Upload, label: "Import", key: "i" },
];
export const OVERSIGHT: NavItem[] = [
  { href: "/audit", icon: ScrollText, label: "Audit", key: "l", show: (r) => allowed(CAN.readAudit, r) },
  { href: "/demo", icon: FlaskConical, label: "Demo controls", key: "c", show: (r) => allowed(CAN.demoControls, r) },
];

export const visibleNav = (items: NavItem[], role: string | undefined) => items.filter((n) => !n.show || n.show(role));
