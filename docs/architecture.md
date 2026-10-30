# Architecture

How the system fits together: pipeline, workflow, data model, deployment layout and project structure. Back to the [README](../README.md).

## Workflow diagrams

Eleven diagrams explain how the system works, from the big picture to individual decisions. GitHub renders them in the browser.

### 1. End-to-end pipeline

How a delay becomes a recovery plan. Dotted lines show where the audit log is written.

```mermaid
flowchart LR
    A[Carrier webhook<br/>or CSV/JSON import] --> B[Ingest guards<br/>signature, idempotency,<br/>stale-event, validation]
    B --> C[Detect<br/>late shipment, supplier delay,<br/>stock shortage]
    C --> D[Impact analysis<br/>earliest-due-date allocation,<br/>before vs after]
    D --> E[Risk ranking<br/>score + factor breakdown]
    E --> F[Recovery options<br/>reallocate, expedite,<br/>alt supplier, split]
    F --> G[AI text<br/>summary, recommendation<br/>among feasible plans]
    G --> H[Propose]
    H --> I[Approve / Reject / Modify<br/>separation of duties]
    I --> J[Confirm and simulate execution]
    J --> K[(Audit log<br/>hash chain)]
    B -.-> K
    C -.-> K
    H -.-> K
    I -.-> K
```

### 2. Plan lifecycle

The states a recovery plan moves through. Proposing, approving, rejecting and confirming execution each need a person with the right role, and every transition is audited.

```mermaid
stateDiagram-v2
    [*] --> DRAFT: options generated
    DRAFT --> PROPOSED: Analyst proposes
    PROPOSED --> APPROVED: right approver, not proposer/modifier
    PROPOSED --> REJECTED: approver rejects with a reason
    APPROVED --> EXECUTING: executor confirms
    EXECUTING --> COMPLETED: preconditions still hold
    APPROVED --> STALE: stock or ETA changed, caught by the re-check at execution
```

### 3. System architecture

The pieces and how they connect. Everything that decides something is in the API; the web app only displays and sends requests.

```mermaid
flowchart LR
    subgraph IN["Data in"]
        CAR["Carrier system<br/>signed webhook"]
        FILES["CSV or JSON files"]
    end
    subgraph WEB["Web app: Next.js"]
        UI["Dashboard, Plans, Approvals,<br/>Audit, Import, Demo controls"]
    end
    subgraph API["API: FastAPI"]
        AUTH["auth<br/>JWT and permission matrix"]
        ING["ingest<br/>webhook and import"]
        RULES["Pure rules<br/>detect, impact, decide, options"]
        ACT["act<br/>plan workflow and<br/>separation of duties"]
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
    AUTH --> AIM
    ING --> RULES
    RULES --> ACT
    ACT --> SIDE
    ING --> DB
    ACT --> DB
    SIDE --> DB
    AIM -.-> LLM
```

### 4. Scenario 1 as a sequence: who does what, and when

The port-delay scenario from the first webhook to a completed plan, showing which role acts at each step.

```mermaid
sequenceDiagram
    autonumber
    participant C as Carrier
    participant A as API
    participant R as Rules
    participant D as Postgres and audit log
    actor AN as Analyst
    actor MG as Manager
    actor OP as Operator

    C->>A: POST /webhooks/carrier, SHP-1042 delayed, signed
    A->>A: check size, signature, idempotency, sequence
    A->>D: store event, move shipment ETA, audit
    A->>R: detect, analyse impact, score risk, build options
    R-->>D: disruption, ranked orders, four DRAFT plans
    AN->>A: open disruption and read the Why? breakdown
    AN->>A: propose the recommended plan
    A->>D: PROPOSED, notify approver, audit
    MG->>A: approve
    A->>A: role allowed, version current, approver is not proposer or modifier
    A->>D: APPROVED, notify operator, audit
    OP->>A: confirm execution
    A->>A: re-check stock and ETA in one transaction
    A->>D: COMPLETED as a simulation, update stock, audit
```

### 5. Carrier webhook: every check, in order

What happens to one incoming event. Every outcome is stored and audited, including the refusals.

```mermaid
flowchart TD
    S["POST /webhooks/carrier"] --> L{"Body over 256 KB?"}
    L -- yes --> R413["413 refused"]
    L -- no --> G{"Signature valid?"}
    G -- no --> R401["401 refused<br/>audited as webhook.unauthorized"]
    G -- yes --> V{"Valid JSON with timezones<br/>and required fields?"}
    V -- no --> R422["422 refused<br/>audited as webhook.invalid"]
    V -- yes --> D{"Idempotency key<br/>seen before?"}
    D -- yes --> DUP["Outcome: duplicate<br/>nothing changes"]
    D -- no --> Q{"Sequence ahead of last_seq<br/>and shipment not delivered?"}
    Q -- no --> STALE["Outcome: stale<br/>nothing changes"]
    Q -- yes --> AP["Outcome: applied<br/>update the shipment"]
    AP --> DET["Run detection"]
```

### 6. Approval gate: why a plan can be blocked

The checks an approval request passes, in the order the service applies them.

```mermaid
flowchart TD
    A["Approve request"] --> R{"Role allowed to approve<br/>this plan type?"}
    R -- no --> F1["Denied and audited"]
    R -- yes --> V{"Plan version matches<br/>what the user saw?"}
    V -- no --> C1["409: reload and retry"]
    V -- yes --> S{"Plan is PROPOSED?"}
    S -- no --> C2["409: not awaiting approval"]
    S -- yes --> P{"Approver is the proposer<br/>or anyone who modified it?"}
    P -- yes --> F2["Blocked, audited as approval_blocked"]
    P -- no --> OK["APPROVED<br/>notify proposer and executor, audit"]
```

### 7. Recovery options: from candidates to a recommendation

Each option is tried on a copy of the current situation and measured by re-running the allocation. The AI only chooses among the feasible results.

```mermaid
flowchart LR
    W["Current situation<br/>stock, inbound, orders"] --> B["Baseline allocation<br/>earliest due date first"]
    W --> X["Apply one option to a copy:<br/>reallocate, expedite,<br/>alternative supplier, split"]
    X --> A2["Re-run the allocation"]
    B --> M
    A2 --> M["Metrics<br/>orders saved, cost,<br/>penalty avoided, net benefit"]
    M --> FQ{"Feasible?"}
    FQ -- no --> INF["Shown with the reasons"]
    FQ -- yes --> PICK["AI recommends one<br/>feasible plan id"]
    PICK --> CHK{"Every number in the text<br/>appears in the input?"}
    CHK -- no --> TPL["Template text is used instead"]
    CHK -- yes --> OUT["Recommendation shown<br/>marked AI"]
```

### 8. Risk score: five factors into one number

Each order gets a score from 0 to 100 and keeps the contribution of every factor, which is what the Why? drawer shows.

```mermaid
flowchart LR
    O["One order"] --> F1["Shortfall<br/>30%"]
    O --> F2["Time slack<br/>25%"]
    O --> F3["Customer tier<br/>20%"]
    O --> F4["SLA penalty<br/>15%"]
    O --> F5["Supplier reliability<br/>10%"]
    F1 --> SUM["Weighted sum<br/>0 to 100"]
    F2 --> SUM
    F3 --> SUM
    F4 --> SUM
    F5 --> SUM
    SUM --> BAND{"Band"}
    BAND -->|"60 or more"| H["High"]
    BAND -->|"30 to 59"| MED["Medium"]
    BAND -->|"under 30"| LOW["Low"]
```

### 9. Audit log: a hash chain

Each row stores the hash of the row before it, so changing or removing any row breaks every hash after it. A database trigger also blocks updates and deletes, and `GET /audit/verify` recomputes the whole chain.

```mermaid
flowchart LR
    R1["Row 1<br/>prev_hash: none<br/>row_hash: H1"] --> R2["Row 2<br/>prev_hash: H1<br/>row_hash: H2"]
    R2 --> R3["Row 3<br/>prev_hash: H2<br/>row_hash: H3"]
    R3 --> RN["Row n<br/>..."]
```

`row_hash` covers the previous hash, time, actor, role, action, entity, reason and payload.

### 10. Data model

How the main tables link. Import batches, import errors and transfer costs are left out to keep it readable.

```mermaid
erDiagram
    WAREHOUSE ||--o{ INVENTORY : holds
    SKU ||--o{ INVENTORY : "stocked as"
    SUPPLIER ||--o{ SHIPMENT : sends
    WAREHOUSE ||--o{ SHIPMENT : receives
    SHIPMENT ||--o{ SHIPMENT_LINE : contains
    SKU ||--o{ SHIPMENT_LINE : "of"
    SHIPMENT ||--o{ SHIPMENT_EVENT : "reported by"
    CUSTOMER ||--o{ ORDER : places
    ORDER ||--o{ ORDER_LINE : contains
    SKU ||--o{ ORDER_LINE : "of"
    WAREHOUSE ||--o{ ORDER_LINE : fulfils
    SHIPMENT ||--o{ DISRUPTION : "late or short"
    DISRUPTION ||--o{ ORDER_RISK : ranks
    ORDER ||--o{ ORDER_RISK : "scored in"
    DISRUPTION ||--o{ PLAN : "has options"
    PLAN ||--o{ PLAN_STEP : "made of"
    USER ||--o{ PLAN : "proposes or approves"
    USER ||--o{ NOTIFICATION : receives
    USER ||--o{ AUDIT_LOG : "acts in"
```

### Deployment layout

Locally everything runs on your machine with Postgres in Docker; in the cloud the three parts are hosted separately.

```mermaid
flowchart LR
    U["Browser"] --> V["Vercel<br/>Next.js web app"]
    V -->|"NEXT_PUBLIC_API_URL"| RN["Render web service<br/>FastAPI"]
    RN --> PG[("Render Postgres")]
    CAR2["Carrier or scenario CLI"] -->|"signed webhook"| RN
    RN -.->|"optional"| LLM2["Anthropic API"]
```

## Architecture and project layout

```
disruptioniq/
├── backend/                  FastAPI service
│   ├── app/
│   │   ├── ingest/           import service, webhook handling, signature check
│   │   ├── detect/           pure detection rules
│   │   ├── impact/           pure earliest-due-date allocation
│   │   ├── decide/           pure risk scoring
│   │   ├── options/          pure recovery-option generators and metrics
│   │   ├── act/              plan state machine, separation of duties, execution
│   │   ├── ai/               the only place an LLM is imported; template fallbacks
│   │   ├── auth/             JWT, permission matrix
│   │   ├── audit/            hash-chained audit log
│   │   ├── notify/           in-app notifications
│   │   ├── demo/             deliberate guard demonstrations
│   │   ├── simulate/         pure what-if engine (supplier shutdown, delay, surge, stock cut)
│   │   ├── synth/            seeded synthetic data generator
│   │   ├── scenarios/        CLI that fires scenarios 1 and 2 through the real endpoints
│   │   ├── routers/          HTTP layer
│   │   └── models.py         SQLAlchemy models (21 tables)
│   ├── alembic/              migrations
│   └── tests/                pytest suite
├── frontend/                 Next.js 16 App Router, React 19, TypeScript
│   ├── app/                  pages: dashboard, disruptions, approvals, what-if lab, audit, import, demo, login
│   ├── components/           dashboard panels, ripple map, plan controls, shared UI
│   └── lib/                  API client, generated OpenAPI types, view-model adapters
├── docker-compose.yml        Postgres 16
├── render.yaml               Render blueprint (API + Postgres)
├── docs/                     architecture, how it works, demo, deployment, roadmap, blueprint
└── CLAUDE.md                 engineering rules for AI-assisted development
```

**Design rules** (from `CLAUDE.md`): detection, impact, risk and option code are pure functions with no database or I/O; services load data, call the rules, and persist results. The LLM client is imported in exactly one module. Permissions are enforced server-side. Every state change writes an audit row.

**Data model.** Linked tables: warehouses, users, suppliers, SKUs, supplier items, inventory, transfer costs, customers, orders and order lines, shipments, shipment lines and shipment events, import batches and errors, disruptions, order risk, plans and plan steps, notifications, and the audit log.

**Stack.**

| Layer | Technology |
|---|---|
| Backend | FastAPI, Pydantic v2, SQLAlchemy 2, Alembic, PyJWT, httpx |
| Database | PostgreSQL 16 |
| Frontend | Next.js 16 (App Router), React 19, TypeScript, Tailwind 4, shadcn/ui, TanStack Query 5 |
| Visuals | Leaflet (route map), React Flow (ripple map), Recharts (charts) |
| AI (optional) | Anthropic API via a single module |
| Tests | pytest |
