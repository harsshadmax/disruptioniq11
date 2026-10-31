const BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
const TOKEN_KEY = "diq_token";

export class ApiError extends Error {
  constructor(public status: number, message: string, public detail?: unknown) {
    super(message);
  }
}

export function getToken(): string | null {
  try {
    return localStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

export function setToken(token: string | null): void {
  try {
    if (token) localStorage.setItem(TOKEN_KEY, token);
    else localStorage.removeItem(TOKEN_KEY);
  } catch {
    /* storage blocked: the session just will not survive a reload */
  }
}

type Opts = { method?: string; body?: unknown; form?: FormData; params?: Record<string, string | number | undefined> };

function describe(detail: unknown): string {
  if (typeof detail === "string") return detail;
  if (detail && typeof detail === "object" && typeof (detail as { message?: unknown }).message === "string") return (detail as { message: string }).message;
  if (Array.isArray(detail)) return detail.map((d) => (d?.msg ? `${(d.loc ?? []).slice(1).join(".")}: ${d.msg}` : String(d))).join("; ");
  return "Request failed";
}

export async function api<T>(path: string, opts: Opts = {}): Promise<T> {
  const url = new URL(path, BASE);
  for (const [k, v] of Object.entries(opts.params ?? {})) if (v !== undefined && v !== "") url.searchParams.set(k, String(v));
  const headers: Record<string, string> = {};
  const token = getToken();
  if (token) headers.Authorization = `Bearer ${token}`;
  let body: BodyInit | undefined;
  if (opts.form) body = opts.form;
  else if (opts.body !== undefined) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(opts.body);
  }
  let res: Response;
  try {
    res = await fetch(url, { method: opts.method ?? (body ? "POST" : "GET"), headers, body });
  } catch {
    throw new ApiError(0, "Cannot reach the server. Is the API running?");
  }
  if (res.status === 401 && path !== "/auth/login") {
    setToken(null);
    // A full page load on purpose: it drops every cached query and any open dialog from the old session.
    // eslint-disable-next-line @next/next/no-location-assign-relative-destination
    if (typeof window !== "undefined" && window.location.pathname !== "/login") window.location.href = "/login";
  }
  const data = await res.json().catch(() => null);
  if (!res.ok) throw new ApiError(res.status, describe(data?.detail), data?.detail);
  return data as T;
}
