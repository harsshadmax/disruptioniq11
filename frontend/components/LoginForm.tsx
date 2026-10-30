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
    <div className="flex min-h-screen items-center justify-center bg-[#e9e6f4] p-4">
      <form onSubmit={submit} className="w-full max-w-sm rounded-[28px] bg-white p-8 shadow-xl shadow-black/5">
        <div className="mb-6 flex items-center gap-3">
          <div className="flex size-11 items-center justify-center rounded-full bg-brand text-lg font-bold text-white">D</div>
          <div className="leading-tight">
            <div className="text-lg font-extrabold text-[#1c1c1e]">DisruptionIQ</div>
            <div className="text-xs text-[#8a8a8f]">From delivery delays to recovery plans</div>
          </div>
        </div>

        <label className="mb-1 block text-xs font-medium text-[#3a3a3f]" htmlFor="email">Email</label>
        <input
          id="email" type="email" required autoComplete="username" value={email} onChange={(e) => setEmail(e.target.value)}
          className="mb-3 h-11 w-full rounded-xl border border-[#e0e0e4] bg-[#f6f4fc] px-4 text-sm outline-none focus:border-brand"
        />
        <label className="mb-1 block text-xs font-medium text-[#3a3a3f]" htmlFor="password">Password</label>
        <input
          id="password" type="password" required autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)}
          className="mb-4 h-11 w-full rounded-xl border border-[#e0e0e4] bg-[#f6f4fc] px-4 text-sm outline-none focus:border-brand"
        />

        {error && <div className="mb-3 rounded-xl bg-[#fdecee] px-3 py-2 text-xs text-[#9b1c2e]">{error}</div>}

        <button
          type="submit" disabled={busy}
          className="flex h-11 w-full items-center justify-center gap-2 rounded-full bg-brand text-sm font-semibold text-white shadow-md shadow-brand/25 disabled:opacity-60"
        >
          {busy && <Loader2 className="size-4 animate-spin" />} Sign in
        </button>

        <div className="mt-6 border-t border-[#f0f0f2] pt-4">
          <div className="mb-2 text-[11px] text-[#8a8a8f]">Demo users (synthetic data). Pick one to fill the form.</div>
          <div className="flex flex-wrap gap-2">
            {DEMO.map((u) => (
              <button
                key={u.email} type="button"
                onClick={() => { setEmail(u.email); setPassword(process.env.NEXT_PUBLIC_DEMO_PASSWORD ?? ""); }}
                className="rounded-full border border-[#e0e0e4] px-3 py-1 text-[11px] font-medium text-[#3a3a3f] hover:border-brand hover:text-brand"
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
