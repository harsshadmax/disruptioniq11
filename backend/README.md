# DisruptionIQ API

FastAPI service that holds all the logic: detection, impact analysis, risk scoring, recovery options, the approval workflow, the audit log and the what-if engine. Python 3.13, PostgreSQL 16.

Setup and run commands are in the [root README](../README.md#run-it-locally). Interactive API docs are served at `/docs`.

## Layout

```
app/
├── routers/    HTTP layer, one file per area
├── ingest/     CSV/JSON import, webhook handling, signature check
├── detect/     pure detection rules
├── impact/     pure earliest-due-date allocation
├── decide/     pure risk scoring
├── options/    pure recovery-option generators and metrics
├── simulate/   pure what-if engine
├── act/        plan state machine, separation of duties, execution
├── ai/         the only place an LLM is imported; template fallbacks
├── auth/       JWT and the permission matrix
├── audit/      hash-chained audit log
├── notify/     in-app notifications
├── demo/       deliberate guard demonstrations
├── synth/      seeded synthetic data generator
├── scenarios/  CLI that fires the two demo scenarios through the real endpoints
└── models.py   SQLAlchemy models
alembic/        database migrations
tests/          pytest suite
```

Rules in `detect/`, `impact/`, `decide/`, `options/` and `simulate/` are pure functions with no database or I/O. Services load data, call the rules and save the results.

## Common commands

```bash
python -m pytest -q                      # run the tests
python -m alembic upgrade head           # apply migrations
python -m app.synth --seed 42 --reset    # reload the synthetic data
python -m app.scenarios s1               # fire demo scenario 1 (or s2)
```

More: [how it works](../docs/how-it-works.md), [configuration](../docs/deployment.md).
