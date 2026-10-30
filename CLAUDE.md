# DisruptionIQ (SIH 2026 PS 1)

Logistics disruption platform: detect delayed shipments, find affected orders, rank risk, recommend recovery, approve with separation of duties, simulate execution, audit everything. Read blueprint.md.

## Non-negotiable rules
1. AI never computes or changes numbers. Inventory, deadlines, risk scores, plan metrics and permissions are deterministic code in detect/, impact/, decide/, options/, act/, auth/. The ai/ module only gets computed JSON and returns text or a choice among given plan ids.
2. ai/ is the only place an LLM client is imported. Every ai function has a template fallback and works with no API key. AI output must pass a check that every number appears in the input.
3. RBAC is enforced in the backend on every route via the permission matrix in auth/permissions.py. Never trust the UI. Warehouse Operators are filtered to their warehouse inside the query.
4. Separation of duties in the service layer: approver != proposer and != any modifier; executor != approver. Admin cannot approve. Blocked attempts are written to the audit log.
5. audit_log is append-only (DB trigger), with prev_hash/row_hash. Every state change, import, webhook outcome and blocked action writes a row.
6. Ingest safety: idempotency key + UNIQUE index; stale events by seq; row-level import validation with error report; plan optimistic locking (409); execution re-checks preconditions in one transaction.
7. Rules are pure functions (no DB, no I/O). Services load data, call rules, persist results.

## Stack
Backend: FastAPI, Pydantic v2, SQLAlchemy 2, Alembic, pytest, Postgres 16 (docker compose).
Frontend: Next.js App Router, TypeScript, Tailwind, shadcn/ui, TanStack Query, React Flow, Recharts.

## Commands
- DB: `docker compose up -d db`
- API: `cd backend && uvicorn app.main:app --reload`
- Tests: `cd backend && pytest -q`
- Seed: `cd backend && python -m app.synth --seed 42`
- Scenarios: `cd backend && python -m app.scenarios s1` (or s2)
- Web: `cd frontend && npm run dev`
- OpenAPI types: `cd frontend && npm run gen:api`

## Conventions
- Type hints everywhere; Pydantic at every boundary.
- Tests first for: permission matrix, SoD, idempotency, stale events, import validation, impact allocation, risk score, plan metrics, optimistic lock, execution rollback, AI number check.
- Use context7 for library docs before writing code against Next.js, shadcn/ui, React Flow, SQLAlchemy.
- Commit per phase after `pytest -q` passes. After any UI change, open the app in the Browser pane and screenshot before saying done.
- UI footer shows "Synthetic demo data".
