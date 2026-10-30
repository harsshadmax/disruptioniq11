"use client";

import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { MAIN, OVERSIGHT, visibleNav } from "./nav";

export const OPEN_SHORTCUTS_EVENT = "diq:shortcuts";
const SEQUENCE_MS = 1500;

const typing = (el: EventTarget | null) => {
  const t = el as HTMLElement | null;
  return !!t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA" || t.tagName === "SELECT" || t.isContentEditable);
};

export function Kbd({ children }: { children: React.ReactNode }) {
  return <kbd className="rounded border border-[#ddd9d0] bg-white px-1.5 py-px text-[10px] font-semibold text-[#4a545e]">{children}</kbd>;
}

/** "G" then a letter jumps to a page; "?" opens the list. Registered once, ignored while typing in a field. */
export function Shortcuts({ role }: { role: string }) {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const pages = useMemo(() => visibleNav([...MAIN, ...OVERSIGHT], role), [role]);

  useEffect(() => {
    let armedAt = 0;
    const onKey = (e: KeyboardEvent) => {
      if (e.ctrlKey || e.metaKey || e.altKey || typing(e.target)) return;
      if (armedAt && Date.now() - armedAt < SEQUENCE_MS) {
        armedAt = 0;
        const page = pages.find((p) => p.key === e.key.toLowerCase());
        if (page) { e.preventDefault(); router.push(page.href); }
        return;
      }
      if (e.key === "g") armedAt = Date.now();
      else if (e.key === "?") { e.preventDefault(); setOpen(true); }
    };
    const onOpen = () => setOpen(true);
    window.addEventListener("keydown", onKey);
    window.addEventListener(OPEN_SHORTCUTS_EVENT, onOpen);
    return () => { window.removeEventListener("keydown", onKey); window.removeEventListener(OPEN_SHORTCUTS_EVENT, onOpen); };
  }, [pages, router]);

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Keyboard shortcuts</DialogTitle>
          <DialogDescription>Shortcuts are ignored while you type in a field.</DialogDescription>
        </DialogHeader>
        <ul className="flex flex-col divide-y divide-[#ebe8e1] text-sm">
          <li className="flex items-center justify-between py-2"><span>Search</span><Kbd>/</Kbd></li>
          <li className="flex items-center justify-between py-2"><span>Show this list</span><Kbd>?</Kbd></li>
          {pages.map((p) => (
            <li key={p.href} className="flex items-center justify-between py-2">
              <span>Go to {p.label}</span>
              <span className="flex items-center gap-1"><Kbd>G</Kbd><span className="text-[10px] text-[#6b7480]">then</span><Kbd>{p.key.toUpperCase()}</Kbd></span>
            </li>
          ))}
        </ul>
      </DialogContent>
    </Dialog>
  );
}
