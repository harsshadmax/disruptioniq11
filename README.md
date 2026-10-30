# DisruptionIQ

From delivery delays to recovery plans (SIH 2026, PS 1). Plan: see `blueprint.md`. Rules for Claude Code: see `CLAUDE.md`.

## Run locally
```bash
docker compose up -d db                 # Postgres on host port 5433; needs Docker Desktop running
cd backend
python -m venv .venv
./.venv/Scripts/python -m pip install -r requirements.txt   # Windows; use .venv/bin on macOS/Linux
./.venv/Scripts/python -m uvicorn app.main:app --reload     # http://localhost:8000/health
./.venv/Scripts/python -m pytest -q
cd ../frontend && npm install && npm run dev                # http://localhost:3000
```

## Status
Phases 0 to 9 done (deploy not performed): scaffold; models, auth, audit; synthetic data, CSV/JSON import, carrier webhook; detection, impact analysis, risk score; recovery options; approval workflow (separation of duties, optimistic locking, stale-plan checks), notifications, simulated execution; AI layer (summary, plan recommendation, order-risk explanation) with template fallbacks; frontend.

Run from `backend/`:
- `python -m app.seed_users` seeds the 5 demo users (credentials in `app/seed_users.py`).
- `python -m app.synth --seed 42 [--reset]` loads repeatable demo data (all of it is synthetic).
- `python -m app.scenarios s1` or `s2` fires a disruption through the real webhook and import endpoints (add `--replay` to resend the last event). The API must be running.
- Import: `POST /import/csv?entity=orders|inventory|shipments` (file upload) and `POST /import/json`. Good rows import, bad rows come back with a reason. A missing timezone on a timestamp is read as UTC.
- Webhook: `POST /webhooks/carrier`, body signed with HMAC-SHA256 in the `X-Signature: sha256=<hex>` header (`WEBHOOK_SECRET`).

- Detection runs after every applied webhook event and every import with good rows, or on demand with `POST /disruptions/detect`. `GET /disruptions`, `GET /disruptions/{id}` (before vs after coverage) and `GET /disruptions/{id}/orders` (ranked, with the factor breakdown). Warehouse operators only see their own warehouse.

- Recovery options: every active disruption gets four DRAFT candidates (reallocate, expedite, alternative supplier, split order), each with cost, orders saved, penalty avoided, net benefit and, if infeasible, the reasons. `GET /disruptions/{id}/plans`; `POST /disruptions/{id}/plans/generate` recomputes them. Orders saved is computed by re-running the allocation with the option applied. Tunable constants (expedite days and fee, alt-supplier fee, split fee) are at the top of `app/options/base.py`.

- AI text (optional): set `ANTHROPIC_API_KEY` (and `ANTHROPIC_MODEL`, default `claude-opus-5-5`). `POST /ai/disruptions/{id}/summary`, `/recommend`, `/orders/{order_id}/explain`, `GET /ai/status`. The AI only restates computed figures or picks one of the feasible plans; any invented number, bad plan id, API error or missing key falls back to a template, and each answer says its `source` (`ai` or `template`). Only `app/ai/client.py` imports the SDK.

- Frontend (`frontend/`, Next.js, needs the API on `NEXT_PUBLIC_API_URL`): login with role badge, dashboard, disruption list and detail ("Why?" drawer with factor bars, before vs after), side-by-side plans with Modify / Propose / Approve / Reject / Confirm execution, approvals queue, audit log with chain check, CSV import with the error report, notification bell. Buttons a role cannot use are hidden or disabled, but the API enforces every rule. After changing the API, run `npm run gen:api` (API must be running) to refresh `lib/api/schema.d.ts`. `npm run lint` and `npm run build` pass.

- Ripple map: the disruption page draws shipment, warehouse, SKU, orders and customers from live data, coloured by risk band, spreading outwards when opened (Replay repeats it). Clicking an order opens its "Why?" drawer.
- Demo controls (Administrator only, `/demo` page or `POST /demo/replay-duplicate|stale-event|self-approval|double-approve`, `GET /demo/targets`): each one runs a real guard on purpose (duplicate webhook, stale event, approval by the proposer or modifier, the same approval twice) and writes a `demo.*` audit row listing every step, next to the rows the guard itself wrote. Self-approval and double approval need a plan in PROPOSED; the double approval really approves it once.

## Hardening (Phase 9)
A code review and a security review of the whole repo led to these changes, each pinned by a test in `backend/tests/test_hardening.py`:
- One in-flight plan per disruption and one active disruption per warehouse/SKU are now enforced by partial unique indexes (migration `a1c2e3f4b5d6`), on top of the service checks. `propose` locks the disruption row and detection takes a Postgres advisory lock, so two simultaneous requests cannot both win.
- Recomputing options updates DRAFT plans in place: ids stay, and a reviewer's Modify survives while it is still feasible.
- `ENVIRONMENT` other than development refuses a default or short `JWT_SECRET` / `WEBHOOK_SECRET`, and `python -m app.seed_users` refuses the public default demo password (set `DEMO_PASSWORD`).
- Webhook bodies over 256 KB are refused (413) before the signature check, counting streamed bytes.
- Login: field length caps, and 8 failed sign-ins in 10 minutes for one email or one address earns a 429 (the first block is audited as `auth.login_blocked`). The counters live in process memory, so with several API instances the limit applies per instance.
- Operators are filtered to their warehouse inside the disruption and plan list queries, and the disruption detail page loads only its own warehouse/SKU cell.
- Known limits: the dashboard still polls several endpoints per disruption; the UI's role lists (`frontend/lib/api/types.ts`, `CAN`) are copies of the permission matrix, and a test fails if they drift; `npm audit` reports 3 low-severity issues in dev tooling only.

## Deploy
Nothing is deployed until you do it; everything below is a manual step.
1. **API and Postgres on Render:** push the repo, then New > Blueprint and select it (`render.yaml`). Fill in `DEMO_PASSWORD` and `CORS_ORIGINS` (the Vercel URL, once you have it) when asked. On every start the service runs `alembic upgrade head`, seeds the demo users, loads the synthetic data the first time, then serves. Check `https://<service>.onrender.com/health`.
2. **Web app on Vercel:** import the repo, set the root directory to `frontend`, and add `NEXT_PUBLIC_API_URL=https://<service>.onrender.com`. Set `NEXT_PUBLIC_DEMO_PASSWORD` to the same value as `DEMO_PASSWORD` only if you want the one-click role buttons on a public demo. Then put the Vercel URL into `CORS_ORIGINS` on Render and redeploy the API.
3. **Scenarios against the deployment:** from `backend/`, run `python -m app.scenarios s1 --base-url https://<service>.onrender.com --password <DEMO_PASSWORD>` with `DATABASE_URL` set to the Render database's external URL (the CLI reads the shipment from the database) and `WEBHOOK_SECRET` set to the deployed value (it signs the event). Otherwise fire the events from your own client with that secret.
4. Free Render services sleep when idle (the first request takes about a minute) and free Postgres expires after 30 days: wake it before a demo, and keep a recorded run as a backup.

Phase 9 code, tests and local scenario runs done; deploy and the backup video are left to you.
