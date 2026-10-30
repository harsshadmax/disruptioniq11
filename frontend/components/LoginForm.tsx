"use client";

import { useState } from "react";
import { Loader2 } from "lucide-react";
import { useAuth } from "@/lib/auth";

// Synthetic demo accounts seeded by backend/app/seed_users.py. The shared demo password is read from the env if set.
const DEMO = [
  { label: "Analyst", email: "analyst@diq.test" },
  { label: "Manager", email: "manager@diq.test" },
  { label: "Operator", email: "operator@diq.test" },
  { label: "Procurement", email: "procurement@diq.test" },
  { label: "Admin", email: "admin@diq.test" },
];

export function LoginForm({ onSuccess }: { onSuccess: () => void }) {
  const { login } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await login(email, password);
      onSuccess();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Sign in failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-[#e6e3dc] p-4">
      <form onSubmit={submit} className="w-full max-w-sm rounded-2xl bg-white p-8 shadow-sm">
        <div className="mb-6 flex items-center gap-3">
          <div className="flex size-11 items-center justify-center rounded-full bg-brand text-lg font-bold text-white">D</div>
          <div className="leading-tight">
            <div className="text-lg font-extrabold text-[#1b2430]">DisruptionIQ</div>
            <div className="text-xs text-[#6b7480]">From delivery delays to recovery plans</div>
          </div>
        </div>

        <label className="mb-1 block text-xs font-medium text-[#2f3944]" htmlFor="email">Email</label>
        <input
          id="email" type="email" required autoComplete="username" value={email} onChange={(e) => setEmail(e.target.value)}
          className="mb-3 h-11 w-full rounded-xl border border-[#d8d4cb] bg-[#f3f1ec] px-4 text-sm outline-none focus:border-brand"
        />
        <label className="mb-1 block text-xs font-medium text-[#2f3944]" htmlFor="password">Password</label>
        <input
          id="password" type="password" required autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)}
          className="mb-4 h-11 w-full rounded-xl border border-[#d8d4cb] bg-[#f3f1ec] px-4 text-sm outline-none focus:border-brand"
        />

        {error && <div className="mb-3 rounded-xl bg-[#f8e4e1] px-3 py-2 text-xs text-[#8c2a22]">{error}</div>}

        <button
          type="submit" disabled={busy}
          className="flex h-11 w-full items-center justify-center gap-2 rounded-lg bg-brand text-sm font-semibold text-white disabled:opacity-60"
        >
          {busy && <Loader2 className="size-4 animate-spin" />} Sign in
        </button>

        <div className="mt-6 border-t border-[#ebe8e1] pt-4">
          <div className="mb-2 text-[11px] text-[#6b7480]">Demo users (synthetic data). Pick one to fill the form.</div>
          <div className="flex flex-wrap gap-2">
            {DEMO.map((u) => (
              <button
                key={u.email} type="button"
                onClick={() => { setEmail(u.email); setPassword(process.env.NEXT_PUBLIC_DEMO_PASSWORD ?? ""); }}
                className="rounded-md border border-[#d8d4cb] px-3 py-1 text-[11px] font-medium text-[#2f3944] hover:border-brand hover:text-brand"
              >
                {u.label}
              </button>
            ))}
          </div>
        </div>
      </form>
    </div>
  );
}
