# DisruptionIQ roadmap

The working list of improvements, in the order we recommend doing them. Update the status column
as each item moves forward. Nothing reaches production until it has been previewed and checked.

**Status key:** `Done` is live in production. `In preview` is built on a branch and being checked. `Planned` is agreed but not started. `Later` is worth doing once real data or time exists. `Not now` is deliberately skipped.

## How a change reaches production

1. Build it on a feature branch (never directly on `main`, because a push to `main` redeploys the live API).
2. Run it locally and look at it in the browser (the preview).
3. Run the checks: backend tests, frontend type-check, lint and build.
4. Show the preview and the results, then wait for a go-ahead.
5. Merge to `main` (Render redeploys the API), run `vercel deploy --prod` from `frontend/` (the web app is not git-connected), and check the live site.
6. Mark the item `Done` below and add a line to the update log.

## Already in production

| Area | What exists |
|---|---|
| Detection | Late shipment, supplier delay and stock shortage, found by fixed rules |
| Impact | Earliest-due-date allocation before and after, ranked order risk (0 to 100, five documented factors) |
| Recovery | Reallocate, expedite, alternative supplier and split-order plans, each checked for feasibility |
| Workflow | Propose, approve, execute with separation of duties, version checks and a hash-chained audit log |
| Data in | Carrier webhook (signed, idempotent, sequence-checked) and CSV/JSON import (10 MB, 10,000 rows) |
| Dashboard | Street map, ripple graph, KPIs, approvals queue, notifications |
| AI | Advisory text only, with template fallbacks and a number guard |
| Hosting | Vercel (web), Render (API), Render Postgres (free tier) |

## Tier 1: features that make the demo stronger

These use data the app already has, so every number is real and explainable.

| # | Feature | Why it matters | Status |
|---|---|---|---|
| 1 | **What-if simulation lab.** Pick a supplier shutdown, a shipment delay, a demand surge or a stock cut (several at once). See orders at risk, units short and penalty exposure, baseline against simulated. Writes nothing to real data. | Answers the jury's first question: "what if this supplier stops?" | Done |
| 1b | Save, reopen and delete simulations; compare recovery strategies inside a simulation | Makes the lab reusable. Needs one new table and migration. | Planned |
| 2 | **Incident replay.** Step through one disruption: detected, plans generated, proposed, approved, executed, with who and when. Built from the existing audit log. | Shows the full story in one screen | Planned |
| 3 | **Resilience scorecard.** A 0 to 100 score from documented rules: supplier dependency, stock cover, supplier reliability, recovery rate. Per-category scores and tips. | One number a manager can track, fully explainable | Planned |
| 4 | **Financial view** by warehouse, supplier and customer, with a downloadable CSV. Estimated values labelled as estimates. | Turns risk into money, which decision makers read first | Planned |
| 5 | **Alert centre.** Group related alerts, acknowledge them, per-user preferences, history. | Stops notification overload | Planned |

## Tier 2: user experience

| # | Feature | Status |
|---|---|---|
| 6 | Keyboard shortcuts that navigate (`G` then a letter, `/` search, `?` help). A command palette (`Ctrl+K`) is still to do. | Shortcuts Done; palette Planned |
| 6b | Sidebar panel: live active-disruption and waiting counts, the three most urgent disruptions with links, a "Run detection now" action, and the shortcut list. Sidebar stays pinned while the page scrolls. | Done |
| 7 | Global search across orders, shipments, suppliers and customers (today it searches disruptions only) | Planned |
| 8 | Loading skeletons, empty states and retry screens on every page | Planned |
| 9 | Report export (CSV now, PDF later) from disruptions, approvals and finance | Planned |
| 10 | Dark mode (in the marine-blue palette) | Later |
| 10b | **Marine-blue retheme.** Warm paper-grey background, ink text, marine blue brand (`#1F4E8C`), brick-red / amber / forest-green risk colours, flat surfaces, 6px corner base, no gradients or glow shadows, neutral icons instead of sparkles, tabular numerals. | Done |
| 11 | Saved filters and dashboard preferences per user | Later |
| 12 | Accessibility pass (focus order, contrast, labels) and a tablet layout check | Planned |
| 13 | "How to read this page" hints for first-time users and jury members | Planned |

## Tier 3: production readiness

| # | Item | Status |
|---|---|---|
| 14 | Admin "reset demo" action, so the jury demo can be re-run without database access | Planned |
| 15 | Keep-alive ping so the free Render service does not sleep before a demo | Planned |
| 16 | GitHub Actions: run backend tests and frontend checks on every pull request | Planned |
| 17 | Move off the free Render Postgres before it expires on **2026-11-29** | Planned (deadline) |
| 18 | Rotate the demo password after the jury demo; remove the public one-click login | Planned |
| 19 | README screenshots and a recorded backup demo video | You (video), Planned (screenshots) |
| 20 | Error monitoring and structured logs | Later |

## Tier 4: experimental, only when labelled honestly

| # | Feature | Condition | Status |
|---|---|---|---|
| 21 | Small ML slice: one delay-probability model and one anomaly detector (scikit-learn only), shown next to the rule-based score | Must say "experimental, synthetic data". No accuracy claims. | Later |
| 22 | AI copilot that answers from the app's own API, with a rules fallback when no AI key is set | Never invents records; respects roles | Later |
| 23 | Geospatial simulation mode (routes, weather, closures) | Must be labelled simulated, not live | Later |
| 24 | Recovery learning (predicted against actual outcomes) | Needs many completed recoveries | Later |

## Not recommended now

Deep learning (LSTM, GRU, Transformer): too little data. A 13-page navigation and a full dark redesign:
a rewrite that risks the working demo. Live traffic, weather and GPS feeds: no provider or credentials.

## Update log

| Date | Change | State |
|---|---|---|
| 2026-10-30 | Roadmap created. What-if simulation lab (item 1) built on `feature/what-if-simulation`: engine, `/simulate` API, "What-if lab" page. Checked: 445 backend tests pass (39 new), type-check, lint and production build clean, run in the browser against the local app. Merged and deployed in `c72e540`. | Done |
| 2026-10-30 | Sidebar filled and pinned (item 6b): Today tiles, Needs attention, Run detection, working `G`-key shortcuts and a `?` help dialog. Checked in the browser (shortcuts, detection button, pinned scroll, tablet layout); type-check, lint and production build clean. Merged and deployed in `c72e540`. | Done |
| 2026-10-30 | Marine-blue retheme (item 10b) applied across all pages: about 370 hardcoded colours mapped to the new palette, corners and shadows flattened, sparkle icons replaced. Checked in the browser (dashboard, What-if lab, disruption detail, sign-in); type-check, lint and production build clean. Merged and deployed in `c72e540`. | Done |
| 2026-10-30 | Deployed `c72e540` (What-if lab, sidebar, shortcuts, marine-blue theme) to Vercel and Render. Checked live: Operator gets 403 on the lab, Analyst, Manager, Procurement and Admin get 200; a supplier-shutdown plus demand-surge run returns baseline against simulated figures; a bad scenario returns 422; disruptions, plans and audit rows are identical before and after a run. The sign-in page shows the new palette. Signed-in pages were not looked at on the live site. | Done |
