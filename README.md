# DisruptionIQ

**From delivery delays to recovery plans.** DisruptionIQ watches inbound shipments and warehouse stock, spots the moment a delay puts customer orders at risk, ranks those orders with a visible explanation, builds four recovery options with their costs, and walks the chosen one through a controlled approval. Every step goes into a tamper-evident audit log.

> **AI advises, logic decides.** Every number (stock, deadlines, risk, cost, permissions) comes from deterministic, tested code. The optional AI layer only writes text about figures already computed. With no API key the product works the same, using template text.

**Live demo:** [web app](https://disruptioniq-sigma.vercel.app) · [API docs](https://disruptioniq-api.onrender.com/docs) (the free API sleeps when idle, so the first request can take about a minute)

All data is **synthetic demo data**. No real customers, suppliers or carriers are involved.

## What it does

| | |
|---|---|
| **Ingest** | CSV or JSON import with row-level validation, plus a signed carrier webhook |
| **Detect** | Late shipments, supplier delays and stock shortages, found by fixed rules |
| **Analyse** | Orders allocated against stock and inbound supply, before and after the delay |
| **Rank** | A 0 to 100 risk score per order from five weighted factors, with a "Why?" breakdown |
| **Recover** | Reallocate, expedite, alternative supplier or split order, each with cost and net benefit |
| **Approve** | Separation of duties and role checks; execution is simulated, never sent to a real system |
| **Contracts** | Upload a customer contract (PDF); the app reads the penalty terms, an AI double-checks them, a manager confirms, and the customer's penalty exposure updates |
| **What-if lab** | Test a supplier shutdown, delay, demand surge or stock cut without touching real data |
| **Audit** | Append-only, hash-chained log with a chain check |

## Architecture and workflow at a glance

GitHub draws the diagrams below in the browser. Eleven more (webhook checks, approval gate, risk score, audit hash chain, data model, a scenario as a sequence) are in [docs/architecture.md](docs/architecture.md).

### System architecture

The web app only displays and sends requests. Everything that decides something is in the API.

```mermaid
flowchart LR
    subgraph IN["Data in"]
        CAR["Carrier system<br/>signed webhook"]
        FILES["CSV or JSON files,<br/>contract PDFs"]
    end
    subgraph WEB["Web app: Next.js on Vercel"]
        UI["Dashboard, route map, Plans,<br/>Approvals, What-if lab,<br/>Contracts, Audit, Import"]
    end
    subgraph API["API: FastAPI on Render"]
        AUTH["auth<br/>JWT and permission matrix"]
        ING["ingest<br/>webhook and import"]
        RULES["Pure rules, no database or I/O<br/>detect, impact, decide, options, simulate"]
        ACT["act<br/>plan workflow and<br/>separation of duties"]
        CON["contracts<br/>PDF terms and review"]
        AIM["ai<br/>text only, template fallback"]
        SIDE["audit and notify"]
    end
    DB[("PostgreSQL 16")]
    LLM["Anthropic API<br/>optional"]

    CAR --> ING
    FILES --> UI
    UI -->|"HTTPS and JWT"| AUTH
    AUTH --> ING
    AUTH --> ACT
    AUTH --> CON
    AUTH --> AIM
    ING --> RULES
    RULES --> ACT
    ACT --> SIDE
    ING --> DB
    ACT --> DB
    CON --> DB
    SIDE --> DB
    AIM -.-> LLM
```

### End-to-end pipeline

How a delay becomes a recovery plan. Dotted lines show where the audit log is written.

```mermaid
flowchart LR
    A["Carrier webhook<br/>or CSV/JSON import"] --> B["Ingest guards<br/>signature, idempotency,<br/>stale event, validation"]
    B --> C["Detect<br/>late shipment, supplier delay,<br/>stock shortage"]
    C --> D["Impact analysis<br/>earliest-due-date allocation,<br/>before vs after"]
    D --> E["Risk ranking<br/>score + factor breakdown"]
    E --> F["Recovery options<br/>reallocate, expedite,<br/>alt supplier, split"]
    F --> G["AI text<br/>summary, recommendation<br/>among feasible plans"]
    G --> H["Propose"]
    H --> I["Approve / Reject / Modify<br/>separation of duties"]
    I --> J["Confirm and simulate execution"]
    J --> K[("Audit log<br/>hash chain")]
    B -.-> K
    C -.-> K
    H -.-> K
    I -.-> K
```

### Plan lifecycle

Each transition needs a person with the right role and is audited.

```mermaid
stateDiagram-v2
    [*] --> DRAFT: options generated
    DRAFT --> PROPOSED: Analyst proposes
    PROPOSED --> APPROVED: right approver, not proposer or modifier
    PROPOSED --> REJECTED: approver rejects with a reason
    APPROVED --> EXECUTING: executor confirms
    EXECUTING --> COMPLETED: preconditions still hold
    APPROVED --> STALE: stock or ETA changed, caught at execution
    COMPLETED --> [*]
    REJECTED --> [*]
```

### Who proposes, approves and executes

The approver and the executor depend on the plan type. Nobody approves their own plan, and the person who approves cannot also execute it.

```mermaid
flowchart LR
    AN["Operations Analyst<br/>reads the Why? breakdown<br/>and proposes"] --> T{"Plan type"}
    T -->|"reallocate<br/>split order"| MG["Supply Chain Manager<br/>approves"]
    T -->|"expedite<br/>alternative supplier"| PA["Procurement Approver<br/>approves"]
    MG --> OP["Warehouse Operator<br/>executes, own warehouse only"]
    PA --> AN2["Operations Analyst<br/>executes"]
    AD["Administrator<br/>cannot approve<br/>manages users, demo controls, audit"]
```

### Request lifecycle inside the API

Every route passes the same path, so a missing permission check fails a test.

```mermaid
flowchart LR
    REQ["HTTP request"] --> RT["Router<br/>parse and validate"]
    RT --> PM{"Permission<br/>for this role?"}
    PM -- no --> D403["403 refused"]
    PM -- yes --> SV["Service<br/>loads rows"]
    SV --> RU["Pure rules<br/>no database, no I/O"]
    RU --> SV2["Service<br/>saves result"]
    SV2 --> AUD["Audit row<br/>and notifications"]
    AUD --> RESP["Typed response"]
```

### AI safety guard: advises, never decides

The AI only writes text about numbers the code has already computed. Any problem falls back to a template, so the product works the same with no API key.

```mermaid
flowchart TD
    F["Facts computed by the rules<br/>customer names never sent"] --> Q{"API key set and<br/>call succeeds in 20 s?"}
    Q -- no --> T["Template text<br/>reason recorded"]
    Q -- yes --> G{"Guard: every number is in<br/>the input, under 700 characters,<br/>no markup or links?"}
    G -- no --> T
    G -- yes --> A["AI text<br/>source = ai"]
    T --> S["Shown with source = template"]
    A --> AU["Audit row<br/>ai.summary or ai.recommend"]
    S --> AU
```

### Safe execution

Approval is not enough: the plan is re-checked against current data at the moment it runs.

```mermaid
flowchart TD
    E["Executor confirms"] --> R{"Role allowed and<br/>not the approver?"}
    R -- no --> B["Blocked and audited"]
    R -- yes --> C{"Stock and ETA still match<br/>what the plan assumed?"}
    C -- no --> ST["Plan becomes STALE<br/>nothing is written"]
    C -- yes --> TX["One transaction:<br/>update stock, steps, disruption"]
    TX --> OK{"Any step fails?"}
    OK -- yes --> RB["Roll back<br/>nothing is written"]
    OK -- no --> DONE["COMPLETED as a simulation<br/>audit and notify"]
```

### Contract review

A customer contract changes penalty exposure only after a person confirms it.

```mermaid
flowchart LR
    UP["Upload contract PDF"] --> RD["Read penalty terms<br/>from the text"]
    RD --> PV["Preview the terms"]
    PV --> CK["AI double-checks<br/>the terms"]
    CK --> DEC{"Manager decides"}
    DEC -- confirm --> CF["Customer penalty<br/>exposure updates"]
    DEC -- reject --> RJ["Contract rejected<br/>nothing changes"]
```

### What-if lab

Test a change on a copy of the current situation. Real data is never touched.

```mermaid
flowchart LR
    SC["Pick a scenario<br/>supplier shutdown, delay,<br/>demand surge, stock cut"] --> CP["Copy current stock,<br/>inbound and orders in memory"]
    CP --> EN["Apply the change and<br/>re-run the same allocation"]
    EN --> CMP["Compare before and after<br/>orders at risk, penalty, cost"]
```

### One typed contract from API to screen

The frontend types are generated from the API, so the two cannot drift apart silently.

```mermaid
flowchart LR
    PY["Pydantic models<br/>in the API"] --> OA["OpenAPI schema<br/>/openapi.json"]
    OA --> TS["openapi-typescript<br/>lib/api/schema.d.ts"]
    TS --> Q["TanStack Query<br/>calls and caching"]
    Q --> UI["Screens<br/>buttons hidden by role,<br/>enforced again by the API"]
```

### Deployment layout

```mermaid
flowchart LR
    U["Browser"] --> V["Vercel<br/>Next.js web app"]
    V -->|"NEXT_PUBLIC_API_URL"| RN["Render web service<br/>FastAPI"]
    RN --> PG[("Render Postgres")]
    CAR2["Carrier or scenario CLI"] -->|"signed webhook"| RN
    RN -.->|"optional"| LLM2["Anthropic API"]
```

## Repository layout

```
disruptioniq/
├── frontend/   Next.js 16 web app (React 19, TypeScript, Tailwind 4)      -> frontend/README.md
├── backend/    FastAPI service, rules, migrations and tests (Python 3.13) -> backend/README.md
├── docs/       architecture, how it works, demo, deployment, roadmap
├── docker-compose.yml   local Postgres 16
├── render.yaml          Render blueprint (API + database)
└── .env.example         every setting, with safe local defaults
```

| Part | Stack | Hosted on |
|---|---|---|
| Web app | Next.js, TanStack Query, Tailwind, Leaflet, Recharts | Vercel |
| API | FastAPI, Pydantic v2, SQLAlchemy 2, Alembic | Render |
| Database | PostgreSQL 16 | Render |

The web app only displays and sends requests. Everything that decides something lives in the API.

## Run it locally

Needs Docker Desktop, Python 3.13 and Node.js 20+.

```bash
docker compose up -d db                                  # Postgres on port 5433

cd backend
python -m venv .venv
./.venv/Scripts/python -m pip install -r requirements.txt   # macOS/Linux: .venv/bin/python
cp ../.env.example .env
./.venv/Scripts/python -m alembic upgrade head
./.venv/Scripts/python -m app.seed_users
./.venv/Scripts/python -m app.synth --seed 42 --reset
./.venv/Scripts/python -m uvicorn app.main:app --reload     # http://localhost:8000/docs

cd ../frontend                                           # in a second terminal
npm install
echo NEXT_PUBLIC_API_URL=http://localhost:8000 > .env.local
npm run dev                                              # http://localhost:3000
```

Sign in as `analyst@diq.test`, `manager@diq.test`, `operator@diq.test`, `procurement@diq.test` or `admin@diq.test` (password `Demo@12345` in development).

## Documentation

| | |
|---|---|
| [Architecture](docs/architecture.md) | Pipeline, plan lifecycle, data model, deployment layout and project structure, with diagrams |
| [How it works](docs/how-it-works.md) | Risk score, recovery options, safety guards, roles and permissions, API routes |
| [Demo walkthrough](docs/demo.md) | The two scripted scenarios and a suggested live flow |
| [Configuration and deployment](docs/deployment.md) | Environment variables, testing, Render and Vercel steps, known limits |
| [Roadmap](docs/roadmap.md) | What is done and what is planned next |
| [Build blueprint](docs/blueprint.md) | The original 10-hour plan and requirement traceability |

## Tests

```bash
cd backend && ./.venv/Scripts/python -m pytest -q     # 445 tests; needs the Postgres container
cd frontend && npm run lint && npm run build
```
