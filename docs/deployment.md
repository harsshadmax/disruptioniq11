# Configuration and deployment

Back to the [README](../README.md).

## Configuration

Copy `.env.example` to `backend/.env` for the API and set `frontend/.env.local` for the web app.

| Variable | Where | Purpose |
|---|---|---|
| `ENVIRONMENT` | backend | `development` allows the defaults; anything else enforces strong secrets |
| `DATABASE_URL` | backend | Postgres URL (`postgres://` and `postgresql://` are accepted and normalised) |
| `JWT_SECRET` | backend | Signs session tokens; 16+ characters outside development |
| `WEBHOOK_SECRET` | backend | HMAC key the carrier uses to sign webhook bodies |
| `DEMO_PASSWORD` | backend | Password for the five demo users; required outside development |
| `CORS_ORIGINS` | backend | Allowed web origins, comma separated |
| `ANTHROPIC_API_KEY`, `ANTHROPIC_MODEL` | backend | Optional. Unset means template text everywhere |
| `NEXT_PUBLIC_API_URL` | frontend | Base URL of the API |
| `NEXT_PUBLIC_DEMO_PASSWORD` | frontend | Optional. Enables one-click role buttons on the login page. Public in the browser bundle: use only on a clearly marked demo deployment |

## Testing

```bash
cd backend
./.venv/Scripts/python -m pytest -q          # 400+ tests; needs the Postgres container running
cd ../frontend
npm run lint
npm run build
```

Tests are written first for the permission matrix, separation of duties, idempotency, stale events, import validation, impact allocation, risk score, plan metrics, optimistic locking, execution rollback and the AI number check. `backend/tests/test_hardening.py` pins every fix from the security review.

## Deployment

Nothing is deployed until you do it; the steps are manual.

1. **API and Postgres on Render:** push the repo, then *New > Blueprint* and select it (`render.yaml`). Fill in `DEMO_PASSWORD` and `CORS_ORIGINS` when asked. On every start the service runs `alembic upgrade head`, seeds the demo users, loads the synthetic data the first time, then serves. Check `https://<service>.onrender.com/health`.
2. **Web app on Vercel:** import the repo, set the root directory to `frontend`, and add `NEXT_PUBLIC_API_URL=https://<service>.onrender.com`. Then put the Vercel URL into `CORS_ORIGINS` on Render and redeploy the API.
3. **Scenarios against the deployment:** from `backend/`, run `python -m app.scenarios s1 --base-url https://<service>.onrender.com --password <DEMO_PASSWORD>` with `DATABASE_URL` set to the Render database's external URL (the CLI reads the shipment from the database) and `WEBHOOK_SECRET` set to the deployed value (it signs the event).
4. Free Render services sleep when idle (the first request takes about a minute) and free Postgres expires after 30 days: wake it before a demo, and keep a recorded run as a backup.

## Hardening and known limits

A code review and a security review of the whole repository led to the fixes pinned in `backend/tests/test_hardening.py`: partial unique indexes for one in-flight plan per disruption and one active disruption per warehouse and SKU; regenerating options updates draft plans in place so a reviewer's edits survive; production secret checks; the webhook size cap; login throttling; and query-level warehouse filtering for operators.

Known limits:
- Login throttling counters live in process memory, so with several API instances the limit applies per instance.
- The dashboard polls several endpoints per disruption.
- The frontend's role lists are copies of the permission matrix (a test fails if they drift).
- `npm audit` reports low-severity issues in development tooling only.
- Execution is a simulation: it updates the database and writes the audit trail, and contacts no external system.
