# How it works

The rules behind the numbers, the guards that keep the data safe, who may do what, and the API. Back to the [README](../README.md).

## How the numbers are computed

Everything in this section is plain, pure functions with unit tests. No AI is involved.

**Impact analysis.** For each warehouse and SKU, demand (orders) is matched against on-hand stock and inbound shipments in earliest-due-date order. Running this twice, with the original and the delayed arrival date, shows which orders are *newly* at risk.

**Risk score (0 to 100)** is a weighted sum of five factors; the breakdown is stored and shown per order:

| Factor | Weight | Meaning |
|---|:-:|---|
| Shortfall | 30% | Share of the order quantity that cannot be covered |
| Time | 25% | Slack between the new arrival and the due date (none or negative = 1.0, up to 2 days = 0.6, else 0.2) |
| Customer tier | 20% | Gold 1.0, Silver 0.7, Bronze 0.4 |
| SLA penalty | 15% | Contract penalty, capped at INR 50,000 |
| Supplier | 10% | Lower supplier reliability (0 to 100) raises the risk |

Bands: **high** at 60 or above, **medium** at 30 or above, otherwise **low**.

**Recovery options** (`backend/app/options/`):

| Option | Idea |
|---|---|
| Reallocate | Move surplus stock from another warehouse, at the lane's transfer cost and lead time |
| Expedite | Pay a fee to pull the inbound shipment forward |
| Alternative supplier | Order from another supplier for the shortfall, at a fee |
| Split order | Ship what is available now and the remainder later |

Each plan reports cost, orders saved, penalty avoided and net benefit. *Orders saved* comes from re-running the allocation with the option applied, not from an estimate. Tunable constants live at the top of `backend/app/options/base.py`.

**AI layer** (`backend/app/ai/`, optional). It writes a disruption summary, recommends one of the feasible plans, and explains one order's risk. Its output must pass a check that every number in it appears in the input; an invented number, an unknown plan id, an API error or a missing key falls back to a template. Each answer reports its `source` (`ai` or `template`). `ai/client.py` is the only file that imports the SDK.

## Safety guards

| Risk | Guard |
|---|---|
| Duplicate carrier event | Idempotency key with a UNIQUE index |
| Out-of-order or stale event | Per-shipment sequence number check |
| Forged webhook | HMAC-SHA256 signature (`X-Signature: sha256=<hex>`), body capped at 256 KB |
| Bad import rows | Row-level validation; good rows load, bad rows come back with a reason |
| Two people editing one plan | Optimistic locking on `version` (409 on conflict) |
| Two simultaneous proposals or detections | Row lock plus Postgres advisory lock, backed by partial unique indexes |
| Plan outdated by new data | Precondition re-check at execution, inside one transaction; a plan that no longer holds becomes STALE |
| Self-approval, double approval | Service-layer separation of duties |
| Silent tampering with history | Audit log is append-only (database trigger) and hash-chained (`prev_hash`, `row_hash`) |
| Credential guessing | 8 failed sign-ins in 10 minutes per email or address returns 429, audited |
| Weak production secrets | `ENVIRONMENT` other than development refuses default or short secrets and the public demo password |
| Operators seeing other sites | Warehouse filter applied inside the query, not after it |

## Roles and permissions

Enforced in the backend on every route (`backend/app/auth/permissions.py`). The UI hides buttons a role cannot use, but it is never the source of truth. A test fails if the frontend's copy of the matrix drifts from the backend's.

| Permission | Analyst | Manager | Operator | Procurement | Admin |
|---|:-:|:-:|:-:|:-:|:-:|
| View disruptions and plans | yes | yes | own warehouse | yes | yes |
| Import data | yes | | | | yes |
| Run detection | yes | yes | | | yes |
| Use AI text | yes | yes | | yes | |
| Propose a plan | yes | | | | |
| Modify a plan | yes | yes | | yes | |
| Approve reallocate / split | | yes | | | |
| Approve expedite / alt supplier | | | | yes | |
| Confirm execution of reallocate / split | | | yes | | |
| Confirm execution of expedite / alt supplier | yes | | | | |
| Read audit log | | yes | | yes | yes |
| Manage users | | | | | yes |
| Demo controls | | | | | yes |

Separation of duties, checked in the service layer: the approver is never the proposer or anyone who modified the plan; the executor is never the approver; the Administrator has no approval rights. Blocked attempts are recorded in the audit log.

## API overview

Interactive docs are served at `http://localhost:8000/docs`. Main routes:

| Area | Routes |
|---|---|
| Auth | `POST /auth/login`, `GET /auth/me` |
| Import | `POST /import/csv?entity=orders\|inventory\|shipments` (file upload), `POST /import/json`, `GET /import/batches`, `GET /import/batches/{id}` |
| Webhook | `POST /webhooks/carrier` |
| Disruptions | `GET /disruptions`, `POST /disruptions/detect`, `GET /disruptions/{id}`, `GET /disruptions/{id}/orders` |
| Plans | `GET /disruptions/{id}/plans`, `POST /disruptions/{id}/plans/generate`, `GET /plans`, `POST /plans/{id}/propose\|modify\|approve\|reject\|execute` |
| AI | `GET /ai/status`, `POST /ai/disruptions/{id}/summary`, `/recommend`, `/orders/{order_id}/explain` |
| Notifications | `GET /notifications`, `POST /notifications/read-all`, `POST /notifications/{id}/read` |
| Audit | `GET /audit`, `GET /audit/verify` |
| Users | `GET /users`, `POST /users` (Administrator) |
| What-if lab | `GET /simulate/options`, `POST /simulate/run` (read-only; Analyst, Manager, Procurement, Admin) |
| Demo controls | `GET /demo/targets`, `POST /demo/replay-duplicate\|stale-event\|self-approval\|double-approve` (Administrator) |
| Health | `GET /health` |

After changing the API, regenerate the frontend types with `npm run gen:api` (API must be running).
