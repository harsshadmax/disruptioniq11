# DisruptionIQ: Build Blueprint (10-hour prototype)

**PS 1: DisruptionIQ - From Delivery Delays to Recovery Plans** (Logistics and Supply Chain Management)

Goal: a working, demo-able prototype in **10 hours, solo, with Claude Code**, that satisfies every "must include" and constraint in the problem statement and shows two disruption scenarios end to end.

**Golden rule: AI advises, logic decides.** AI writes summaries and recommends *among* plans the rules already built. Inventory maths, deadlines, risk scores and permissions are deterministic code.

---

## 1. Requirement traceability (what judges will check)

| PS requirement | Where it is built | Proof in demo / tests |
|---|---|---|
| CSV/JSON import | `ingest/import_service.py`, `POST /import/{csv\|json}` | Upload a good file, then a bad file; see row-level errors |
| At least one simulated carrier webhook | `POST /webhooks/carrier`, `scenarios` CLI fires events through it | Scenario 1 starts with a webhook |
| Linked data model | Section 6 tables with foreign keys | ERD in README, FK integrity test |
| Detect late shipments, supplier delays, stock shortages | `detect/` (pure rules) | Unit tests per rule; alerts list in UI |
| Impact analysis | `impact/` earliest-due-date allocation, before vs after delay | "5 orders newly at risk" panel |
| Risk ranking with factor explanation | `decide/risk.py`, factor breakdown stored per order | Ranked table plus "Why?" panel with factor bars |
| AI-assisted recovery options (reallocate, expedite, alternative supplier, split order) | `options/` generates candidates and metrics (rules); `ai/` recommends and explains | Plan comparison screen |
| Approve / reject / modify, execution simulated only after confirmation | `act/` state machine | Modify recomputes metrics; execute is blocked until approved and confirmed |
| Notifications | `notifications` table + bell UI | Proposer and approver notified on each transition |
| Full audit trail | append-only `audit_log` (DB trigger) | Audit page, filters, hash chain check |
| Dashboard: disruptions, affected orders, pending approvals, recovery progress | `GET /dashboard`, dashboard page | Four KPI tiles plus lists |
| Backend-enforced RBAC, 5 roles, no self-approval | `auth/` dependency + permission matrix, SoD in service layer | Parametrised permission test; blocked self-approval in audit |
| Persistent database | PostgreSQL (docker compose locally, Render in cloud) | Restart containers, data survives |
| Synthetic data of our own | `app/synth/` seeded generator | `python -m app.synth --seed 42` is repeatable |
| Two disruption scenarios | `app/scenarios/s1.py`, `s2.py` | Demo script, section 12 |
| AI for summaries and recommendations only | `ai/` module, validated output, template fallback | Test: app works with no API key; numbers in AI text must exist in input |
| Duplicates, invalid data, conflicting updates handled safely | Idempotency key, `seq` stale check, row validation, optimistic locking, precondition re-check at execution | Tests plus live "replay duplicate / stale event / double-approve" buttons |

---

## 2. The two disruption scenarios

**Scenario 1: Port delay on an inbound supplier shipment** (late shipment + supplier delay)
- Carrier webhook says shipment `SHP-1042` from supplier *Coastal Polymers* is delayed, ETA moves from day 3 to day 9, into Chennai warehouse.
- Result: 5 to 7 customer orders newly at risk (mix of Gold, Silver, Bronze, some with SLA penalties).
- Best recovery: reallocate from Bengaluru for the urgent orders, expedite the rest, alternative supplier as the costly third option.

**Scenario 2: Partial shipment plus demand spike** (stock shortage)
- Supplier *Metro Components* delivers 55% of a PO into Mumbai. A burst of new orders for the same SKU arrives.
- Result: projected stock runs out before the next replenishment; 4 to 6 orders at risk.
- Best recovery: split orders (ship available now, remainder later), alternative supplier, a small reallocation from Delhi.

Both scenarios are triggered by a CLI that sends events through the **real** webhook and import endpoints, so every guard (idempotency, validation, audit) is exercised on camera.

---

## 3. Stack (chosen for speed with Claude Code)

| Layer | Choice | Why |
|---|---|---|
| Frontend | Next.js (App Router) + TypeScript + Tailwind + **shadcn/ui** + TanStack Query | Claude writes this reliably; shadcn gives tables, dialogs, badges instantly |
| Graph and charts | React Flow (ripple map), Recharts (KPIs) | Ripple map is the memorable visual |
| Backend | FastAPI + Pydantic v2 | Validation at every boundary, auto OpenAPI |
| DB | PostgreSQL 16, SQLAlchemy 2, Alembic | Unique constraints for idempotency, triggers for immutable audit |
| Auth | JWT login with seeded users, role checked on every route | Real backend-enforced RBAC, no UI-only checks |
| AI | Claude API through **one** module, template fallback | Keeps the rule enforceable and the demo safe |
| Tests | pytest (rules, guards, permission matrix), one Playwright demo test if time | Trust story is the product |
| Local run | Docker Compose (db, api, web) | One command |
| Deploy | Render (API + Postgres), Vercel (web) | Optional in the last hour |

Architecture: **modular monolith**, one FastAPI app, one DB.

```
Next.js UI --REST/JSON--> FastAPI
  auth/        JWT, roles, permission matrix, scope (warehouse)
  ingest/      CSV/JSON import, validation, carrier webhook, idempotency, seq check
  detect/      late shipment, supplier delay, stock shortage (pure rules)
  impact/      earliest-due-date allocation, before vs after, affected orders
  decide/      risk score + factor breakdown, supplier reliability
  options/     reallocate, expedite, alt supplier, split: candidates + metrics (pure)
  act/         plan state machine, approve/reject/modify, SoD, execute (simulated)
  notify/      in-app notifications
  audit/       append-only log + hash chain
  ai/          summarize, recommend (validated), explain; fallbacks
  PostgreSQL
```

---

## 4. Roles, permissions and separation of duties

| Action | Ops Analyst | Supply Chain Manager | Warehouse Operator | Procurement Approver | Administrator |
|---|---|---|---|---|---|
| View dashboard, disruptions, orders | yes | yes | own warehouse only | yes | yes |
| Import data (CSV/JSON) | yes | no | no | no | yes |
| Generate options, create draft plan | yes | yes | no | no | no |
| Submit plan for approval (propose) | yes | no | no | no | no |
| Modify a plan | yes (draft) | yes (creates new version) | no | yes (creates new version) | no |
| Approve / reject: reallocate, split | no | **yes** | no | no | no |
| Approve / reject: expedite, alternative supplier | no | no | no | **yes** | no |
| Confirm execution: reallocate, split | no | no | **yes** | no | no |
| Confirm execution: expedite, alternative supplier | yes | no | no | no | no |
| Manage users, thresholds | no | no | no | no | yes |
| Read full audit log | no | yes | no | yes | yes |
| Own notifications | yes | yes | yes | yes | yes |

**Separation-of-duties rules (backend service layer, not UI):**
1. `approver != proposer` and `approver != anyone who modified the plan`.
2. `executor != approver`.
3. Every blocked attempt writes `approval_blocked` or `execution_blocked` to the audit log with the reason.
4. Administrator has **no** approval rights, so admin cannot rubber-stamp.
5. Warehouse Operator queries are filtered to their assigned warehouse inside the query itself.

Stretch (only if ahead): plans with cost above a threshold need two approvals from two different roles.

---

## 5. Safe handling of bad inputs

| Risk | Handling |
|---|---|
| Duplicate event | `idem_key = sha256(carrier\|shipment_ref\|event_type\|occurred_at_bucket)` with a UNIQUE index; second insert returns `200 duplicate` and is audited |
| Out-of-order or stale event | Each event carries `seq`; if `seq <= shipment.last_seq` it is stored as `stale`, ignored, and audited |
| Invalid data (import) | Row-level validation (types, positive qty, known FKs, due date after order date); good rows import, bad rows go to `import_errors` with a reason; batch summary returned |
| Invalid webhook payload | Pydantic validation, `422` plus audit row |
| Conflicting updates to a plan | `plans.version` optimistic lock; a second concurrent approve gets `409 Conflict` |
| World changed after approval | At execution, preconditions are re-checked (stock still available, shipment still open). If not, plan becomes `STALE` and must be re-evaluated; nothing is half-applied (single DB transaction) |
| Tampering | `audit_log` UPDATE/DELETE blocked by trigger; each row stores `prev_hash` and `row_hash` |

---

## 6. Data model (linked)

| Table | Key columns |
|---|---|
| `users` | id, name, email, password_hash, role, warehouse_id (nullable, for operators) |
| `suppliers` | id, name, baseline_lead_days, reliability_score |
| `supplier_items` | supplier_id, sku_id, unit_price, lead_days (used for alternative supplier option) |
| `warehouses` | id, name, city |
| `skus` | id, name, unit_cost, safety_stock_default |
| `inventory` | warehouse_id, sku_id, on_hand, safety_stock, version |
| `customers` | id, name, city, tier (`gold`/`silver`/`bronze`), allows_partial |
| `orders` | id, customer_id, order_date, due_date, status, sla_penalty, value |
| `order_lines` | id, order_id, sku_id, warehouse_id (fulfilment), qty, qty_allocated |
| `shipments` | id, ref, supplier_id, carrier, dest_warehouse_id, promised_eta, current_eta, status, last_seq, last_scan_at, version |
| `shipment_lines` | shipment_id, sku_id, qty_expected, qty_received |
| `shipment_events` | id, shipment_id, carrier, event_type, seq, payload_json, idem_key (**unique**), outcome (`applied`/`duplicate`/`stale`/`invalid`) |
| `transfer_costs` | from_warehouse_id, to_warehouse_id, cost_per_unit, transit_days |
| `import_batches`, `import_errors` | batch_id, source, rows_ok, rows_failed; row_no, field, reason |
| `disruptions` | id, type (`late_shipment`/`supplier_delay`/`stock_shortage`), shipment_id?, sku_id?, warehouse_id?, severity, status, detected_at, summary_text |
| `order_risk` | disruption_id, order_id, score, band, factors_json, rank |
| `plans` | id, disruption_id, type (`reallocate`/`expedite`/`alt_supplier`/`split`), params_json, metrics_json, status, version, proposer_id, modified_by_ids, approver_id, executor_id, ai_rationale |
| `plan_steps` | plan_id, seq, description, status, done_at (drives recovery progress) |
| `notifications` | id, user_id, kind, message, entity_ref, read_at |
| `audit_log` | id, ts, actor_id, role, action, entity_type, entity_id, reason, payload_json, prev_hash, row_hash (**no UPDATE/DELETE**) |

Plan status machine: `DRAFT -> PROPOSED -> APPROVED | REJECTED -> EXECUTING -> COMPLETED`, plus `STALE`, `CANCELLED`. A modify on `PROPOSED` creates a new version, returns to `PROPOSED`, and adds the modifier to `modified_by_ids`.

---

## 7. Deterministic rules spec (all pure functions, all unit-tested)

**7.1 Detection**
- **Late shipment:** `current_eta > promised_eta`, or webhook `status = delayed`, or `hours_since_last_scan > 3 x route_median_scan_gap`.
- **Supplier delay:** supplier's open shipments with `delay_days > threshold`, or mean of last 3 lead times `> 1.25 x baseline_lead_days`, or partial receipt (`qty_received < qty_expected`).
- **Stock shortage:** `projected_available(warehouse, sku, date) < demand` or `< safety_stock` (see 7.2).

**7.2 Impact analysis (earliest-due-date allocation)**
For each `(warehouse, sku)`:
1. Supply timeline = `on_hand now` plus each inbound shipment line at its ETA.
2. Sort open orders by `due_date`, then tier.
3. Walk orders in order; an order is **covered** if cumulative demand up to it is `<= supply that has arrived by (due_date - handling_days)`.
4. Run twice: once with `promised_eta`, once with `current_eta`. **Affected orders** = covered before, uncovered now. Also record partially covered ones.

**7.3 Risk score (0 to 100), stored with its factors**
```
shortfall_ratio = uncovered_qty / order_qty                     (0..1)
slack_days      = due_date - earliest_possible_fulfil_date
time_risk       = 1.0 if slack_days <= 0 else 0.6 if slack_days <= 2 else 0.2
tier_weight     = gold 1.0, silver 0.7, bronze 0.4
penalty_weight  = min(1, sla_penalty / 50000)
supplier_risk   = 1 - supplier_reliability / 100
score = 100 * (0.30*shortfall_ratio + 0.25*time_risk + 0.20*tier_weight
             + 0.15*penalty_weight + 0.10*supplier_risk)
band  = high >= 60, medium 30..59, low < 30
```
Each factor's contribution (weight x value) is stored so the "Why?" panel can show bars and plain text like "Gold customer: +20".

**7.4 Supplier reliability (0 to 100)**
`100 x (0.6*on_time_rate + 0.25*(1 - partial_rate) + 0.15*(1 - min(1, leadtime_stddev/leadtime_mean)))`

**7.5 Recovery option generators (pure; each returns params plus metrics)**
- **Reallocate:** candidate source warehouses with `surplus = on_hand - committed_demand - safety_stock > 0`; qty = min(shortfall, surplus); `cost = qty x transfer cost`; `arrival = today + transit_days`.
- **Expedite:** for the delayed shipment, `new_eta = current_eta - expedite_days_available`; `cost = qty x expedite_fee`.
- **Alternative supplier:** from `supplier_items`, pick suppliers with `lead_days` that beat the new ETA; `cost = qty x (unit_price - current_price) + fixed fee`; rank by reliability.
- **Split order:** only if `customer.allows_partial`; ship `available_now`, remainder at the new supply date; `cost = extra shipment fee`.
- **Metrics for every option:** `orders_saved`, `orders_still_late`, `cost`, `penalty_avoided`, `net_benefit = penalty_avoided - cost`, `new_eta`, `stock_left_at_source`, `feasible` plus reasons. Metrics are produced by re-running 7.2 with the option applied.

**7.6 Execution (simulated, one transaction)**
Re-check preconditions, then apply effects: move inventory rows (with `version` check), create or update inbound shipment, update ETAs, mark order lines allocated, mark steps done, re-run risk, write audit and notifications. Any failed check rolls back and sets `STALE`.

**7.7 Deadlines and notifications:** approval SLA timer (for example 2 hours): plans pending longer are flagged "overdue" on the dashboard and re-notify the approver.

---

## 8. AI layer (the only place an LLM is called)

Functions in `ai/`:
- `summarize_disruption(context_json)` returns a 3 to 4 sentence plain summary.
- `recommend(plans_json, context_json)` returns `{recommended_plan_id, rationale}`.
- `explain_order_risk(order_factors_json)` returns a plain sentence.
- (stretch) `draft_customer_notice(order_json)`.

**Guardrails (each has a test):**
1. The AI receives already-computed JSON and may only restate or choose from it.
2. `recommended_plan_id` must be one of the generated candidates, else fall back.
3. Post-check: every number in the AI text must appear in the input JSON, else use the template.
4. Template fallback for every function, so the app works with no API key or on API error.
5. AI never touches inventory, deadlines or permissions, and cannot approve or execute anything.
6. Use the `claude-api` skill for the SDK call; the model id comes from an env var.

---

## 9. Time plan (10 hours)

| Hours | Phase | Output |
|---|---|---|
| 0:00 to 0:45 | **P0 Scaffold** | Repo, docker compose, FastAPI + Next skeleton, `CLAUDE.md` |
| 0:45 to 1:45 | **P1 Models, auth, audit** | Migrations, audit trigger and hash chain, JWT login, 5 seeded users, permission matrix test |
| 1:45 to 2:45 | **P2 Synthetic data, import, webhook** | Generator, CSV/JSON import with error report, webhook with idempotency and seq check |
| 2:45 to 4:15 | **P3 Detect, impact, risk** | Rules plus tests; `/disruptions`, `/disruptions/{id}/orders` |
| 4:15 to 5:15 | **P4 Recovery options** | Four generators plus metrics; `/disruptions/{id}/plans` |
| 5:15 to 6:15 | **P5 Workflow, notifications, execution** | State machine, SoD, optimistic lock, simulated execution, notifications |
| 6:15 to 6:45 | **P6 AI layer** | Summaries, recommend, fallbacks, guard tests |
| 6:45 to 8:30 | **P7 Frontend** | Login, dashboard, disruption detail, plan compare and approvals, audit, import, notifications |
| 8:30 to 9:15 | **P8 Ripple map and demo controls** | React Flow graph; buttons to replay duplicate, stale, self-approve |
| 9:15 to 10:00 | **P9 Harden and ship** | `code-review`, `security-review`, bug fixes, demo run, backup recording; deploy only if on schedule |

**Cut lines if you fall behind (cut in this order):** deploy, customer notice draft, two-approval stretch, ripple map (replace with a simple impact table), Playwright test. **Never cut:** RBAC and SoD tests, idempotency, audit trail, the two scenarios, the dashboard.

**Checkpoints:** end of hour 4:15 you must see ranked at-risk orders for Scenario 1 via API. End of 6:15 an end-to-end approve and execute via API/curl. End of 8:30 full demo clickable.

---

## 10. Claude Code setup

### 10.1 Working method
- Keep this file as `blueprint.md` in the repo root; start each session with "read blueprint.md and CLAUDE.md".
- **Plan mode first** for P3, P4 and P5, then approve and implement.
- **Tests first** for rules, guards and the permission matrix.
- One phase per branch, `/code-review` before merging, commit at the end of each phase.
- Freeze the **API contract** after P5: export `openapi.json`, generate TS types (`openapi-typescript`), then the frontend can be built against it.
- Use `/compact` when a session gets long; if confused, start fresh and point at the failing test.

### 10.2 MCP servers
| MCP | Use |
|---|---|
| **Context7** | Fresh docs for Next.js, shadcn/ui, TanStack Query, React Flow, FastAPI, SQLAlchemy 2, Alembic. Add "use context7" to prompts |
| **Built-in Browser** | Open the running app, click through both scenarios, screenshot each page, read console errors, after every frontend phase |
| **Render MCP** | Create Postgres and web service, read deploy logs (only if deploying) |
| **Vercel MCP** | Deploy the web app, read build logs (only if deploying) |
| **Postman MCP** | Optional: collection from the OpenAPI file |

Servers that need sign-in must be authorised via `/mcp` in an interactive `claude` terminal first.

### 10.3 Skills
| Skill | When |
|---|---|
| `init` | Generate the first `CLAUDE.md`, then replace with section 11 |
| `fastapi-backend-architect` | P0 to P2 scaffolding (routers, schemas, SQLAlchemy) |
| `claude-api` | P6 AI module (SDK usage, model id, error handling) |
| `run` | Launch the app and verify changes in the real UI |
| `simplify` | After each module works |
| `code-review` | Before each merge (`/code-review high`) |
| `security-review` | After P1 (auth), P5 (workflow) and P6 (AI input handling) |
| `dataviz` | KPI tiles and charts on the dashboard |
| `update-config` | Add a hook that runs `pytest -q` after backend edits |
| `render:render-deploy`, `render:render-blueprints`, `render:render-postgres`, `render:render-debug` | P9 deploy |
| `design:design-critique`, `design:accessibility-review` | Optional polish |

### 10.4 Parallel work (saves 1 to 2 hours)
After P5, run **two sessions on separate branches or worktrees**: one for the frontend (P7) against the frozen OpenAPI types, one for the AI layer plus ripple map (P6, P8). Never let two sessions edit the same files. Use the **Explore** agent for read-only questions ("where is the SoD check enforced?").

---

## 11. `CLAUDE.md` (paste into repo root)

```markdown
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
```

---

## 12. Phase prompts (paste one at a time)

### P0 Scaffold
> Read blueprint.md and CLAUDE.md. Scaffold the repo: FastAPI app with `/health`, module folders from section 3, Alembic, Next.js app with Tailwind and shadcn/ui, docker-compose with Postgres 16, `.env.example`. Use context7 for Next.js and shadcn setup. No features yet.

**Done when:** `docker compose up -d db`, `/health` returns ok, frontend loads.

### P1 Models, auth, audit
> Implement the tables in section 6 as SQLAlchemy models plus an Alembic migration. Add an audit trigger that blocks UPDATE and DELETE on `audit_log`, and an audit writer that sets `prev_hash` and `row_hash`. Implement JWT login and `auth/permissions.py` with the matrix from section 4 as data. Seed 5 users, one per role (operator assigned to Chennai). Tests first: audit immutability, hash chain verification, and a parametrised test that every route returns 403 for every role not allowed.

**Done when:** tests green; login works for all 5 roles.

### P2 Synthetic data, import, webhook
> Write `app/synth` (seeded RNG): 6 suppliers, 4 warehouses (Chennai, Bengaluru, Mumbai, Delhi), 20 SKUs, 12 customers across tiers, about 60 orders with lines, 15 shipments, inventory, transfer costs, supplier items. Then `ingest/`: `POST /import/csv` and `/import/json` with row-level validation and an `import_errors` report; `POST /webhooks/carrier` with Pydantic validation, idempotency key and `seq` stale check. Tests first: duplicate, stale, invalid payload, bad CSV rows (good rows still import), and repeatability of the generator.

**Done when:** a bad CSV imports its good rows and reports the bad ones; duplicate and stale webhooks are audited.

### P3 Detect, impact, risk (plan mode first)
> Implement `detect/`, `impact/` and `decide/` as pure functions per section 7.1 to 7.4. Write tests first using fixtures that mirror Scenario 1 and 2. Services persist `disruptions` and `order_risk` with factor breakdowns. Endpoints: `GET /disruptions`, `GET /disruptions/{id}`, `GET /disruptions/{id}/orders` (ranked, with factors). Show before-vs-after covered orders.

**Done when:** after firing Scenario 1, the API returns ranked at-risk orders with factors and a "newly at risk" count.

### P4 Recovery options
> Implement the four generators in `options/` per 7.5, each returning params and metrics by re-running impact with the option applied. Endpoint: `GET /disruptions/{id}/plans` returns candidates with `feasible` and reasons. Tests: for both scenarios at least two feasible options with different cost and orders_saved; infeasible cases (no surplus, customer disallows partial) are reported, not hidden.

**Done when:** Scenario 1 shows reallocate, expedite and alt supplier; Scenario 2 shows split and alt supplier.

### P5 Workflow, notifications, execution (plan mode first)
> Implement `act/` per sections 4, 5 and 7.6: create draft, propose, modify (new version, recompute metrics), approve, reject, confirm execution. Enforce roles by plan type, SoD, optimistic locking, precondition re-check, single-transaction execution with `plan_steps`, notifications on each transition, audit rows for every action including blocked ones. Tests first: self-approval blocked, modifier cannot approve, admin cannot approve, wrong role gets 403, double approve gives 409, stock changed before execute gives STALE and no partial write.

**Done when:** a full propose, approve, execute run via curl; all guard tests green. Run `security-review` on `auth/` and `act/`.

### P6 AI layer
> Use the claude-api skill. Implement `ai/` per section 8 with fallbacks and the number post-check. Store `summary_text` on disruptions and `ai_rationale` on plans. Tests: no API key still works; invalid plan id falls back; a number not in the input triggers the fallback.

### P7 Frontend (separate session, uses OpenAPI types)
> Using context7 for shadcn and TanStack Query, build: login with role badge; dashboard (KPI tiles: active disruptions, affected orders, pending approvals, recovery progress; lists below); disruption page (AI summary, ranked orders table, "Why?" drawer with factor bars, before-vs-after covered orders); plans page (compare options side by side, recommended badge, Modify dialog, Approve and Reject only for allowed roles); execution confirmation for the right role; approvals queue; audit page with filters; import page with the error report; notification bell. Hide what a role cannot do, but never rely on that. Then run the app, log in as each role, screenshot every page.

### P8 Ripple map and demo controls
> Add a React Flow view: delayed shipment, warehouse, SKUs, orders, customers, coloured by risk band, animated spread when opened; click an order for its factors. Add a "Demo controls" panel (Administrator only): replay duplicate webhook, send stale event, attempt self-approval, double approve in two tabs; results must appear in the audit page within a second.

### P9 Harden and ship
> Run `/code-review high` and `/security-review` on the whole repo, fix findings, run the full test suite, then run both scenarios start to finish in the Browser pane and fix anything broken. If on schedule, deploy: write `render.yaml`, deploy the API and Postgres to Render and the web app to Vercel, run migrations and seed, and read logs if anything fails. Record a backup demo video.

---

## 13. Demo script (about 5 minutes)

1. **Login as Operations Analyst.** Dashboard shows nothing active. Upload a CSV with two bad rows: good rows import, bad rows listed with reasons.
2. **Scenario 1:** fire the carrier webhook (port delay). A disruption appears; AI summary appears; "5 orders newly at risk".
3. Open the **ranked orders**; click the top Gold order: factor bars explain why. Show the ripple map spreading.
4. **Plans:** compare Reallocate vs Expedite vs Alternative supplier (cost, orders saved, penalty avoided, new ETA). Note the AI-recommended plan and its rationale.
5. Propose Reallocate. **Switch to Analyst trying to approve:** blocked (403, audited).
6. **Login as Supply Chain Manager:** modify the transfer quantity (metrics recompute), approve. Log in as the same Manager and try to approve a plan they modified: blocked.
7. **Login as Warehouse Operator (Chennai):** sees only their warehouse; confirms execution. Dashboard recovery progress moves; notifications fire.
8. **Guards live (Administrator demo controls):** replay duplicate webhook (ignored), stale event (rejected), double approve (409).
9. **Scenario 2:** partial shipment plus demand spike; show split order and alternative supplier; approve as **Procurement Approver**.
10. Close on the **audit trail** with the hash chain check and the 5-minute story: "detect, rank, recommend, approve, execute, prove."

---

## 14. Final checklist

- [ ] CSV and JSON import with row-level error report
- [ ] Carrier webhook: duplicate ignored, stale rejected, invalid rejected, all audited
- [ ] Linked model with FK integrity; data persists across restart
- [ ] Late shipment, supplier delay and stock shortage all detected
- [ ] Impact shows newly-at-risk orders (before vs after)
- [ ] Ranked orders with factor explanation
- [ ] Four recovery option types generated with rule-computed metrics
- [ ] AI recommendation validated; app works with no API key
- [ ] Approve, reject, modify; execution only after approval and confirmation
- [ ] 5 roles enforced in the backend; permission matrix test green
- [ ] No self-approval; modifier cannot approve; admin cannot approve; executor is not approver
- [ ] Double approve gives 409; changed stock gives STALE with no partial write
- [ ] Notifications and full audit trail (hash chain verifies)
- [ ] Dashboard: active disruptions, affected orders, pending approvals, recovery progress
- [ ] Two scenarios demonstrated end to end
- [ ] "Synthetic demo data" shown in the UI; README with ERD and run steps
- [ ] Demo rehearsed twice; backup recording saved
