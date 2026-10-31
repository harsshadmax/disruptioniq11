# Demo walkthrough

Back to the [README](../README.md).

Two scripted scenarios fire events through the **real** webhook and import endpoints, so every guard runs for real. The API must be running and the demo data loaded.

```bash
cd backend
./.venv/Scripts/python -m app.scenarios s1            # Scenario 1
./.venv/Scripts/python -m app.scenarios s2            # Scenario 2
./.venv/Scripts/python -m app.scenarios s1 --replay   # resend the last event: the duplicate guard rejects it
```

**Scenario 1: port delay.** Carrier webhook pushes shipment `SHP-1042` (supplier *Coastal Polymers* into the Chennai warehouse) six days late. Six to seven Chennai orders become at risk. The best option is typically to reallocate stock from Bengaluru.

**Scenario 2: partial delivery plus demand spike.** Shipment `SHP-1077` (*Metro Components* into Mumbai) delivers 55% of the order, then a burst of four new Mumbai orders is imported. Projected stock runs out before the next delivery.

**Showcase data (optional).** To browse a lived-in system instead of two fresh disruptions, load the showcase after the base data: `python -m app.synth.showcase` (add `--dry-run` to preview). It adds situations in all four cities (late shipments, a partial delivery, a stock count gap, a silent carrier) and moves their plans through every status: waiting for approval, approved and waiting for the operator, completed, rejected, and stale. It also leaves refused requests, duplicate and out-of-order carrier events, and an import with rejected rows. Everything goes through the real importers, webhook processor and approval workflow. It does not touch `SHP-1042` or `SHP-1077`, so the two scenarios above still run live afterwards. Against a deployed API (no database access needed): `python -m app.synth.showcase --api https://<service>.onrender.com --password <DEMO_PASSWORD> --webhook-secret <WEBHOOK_SECRET> --base-date <day the base data was loaded>`. To start over locally: `python -m app.synth --seed 42 --reset`, then the showcase again (the audit log is append-only and keeps earlier runs).

Suggested live flow:

1. Sign in as the **Analyst**, fire a scenario, open the new disruption, and click an order to see the *Why?* factor breakdown.
2. Compare the four plans side by side, then **Propose** the recommended one.
3. Sign in as the **Manager** (or Procurement, depending on plan type) and **Approve**. Try approving as the Analyst to see the blocked attempt appear in the audit log.
4. Sign in as the **Operator** and confirm execution of a reallocate plan; watch recovery progress change.
5. Open **Audit** as Manager and run the chain check.
6. As **Admin**, open **Demo controls** to trigger a duplicate webhook, a stale event, a self-approval and a double approval on purpose. Each runs a real guard and writes a `demo.*` audit row.
