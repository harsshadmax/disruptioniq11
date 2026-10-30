from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.routers import ai, audit, auth, demo, disruptions, imports, notifications, plans, users, webhooks

app = FastAPI(title="DisruptionIQ API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.cors_origins.split(",")],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Single list of routers: main includes them and tests/test_route_permissions.py walks them.
ROUTERS = [auth.router, users.router, audit.router, imports.router, webhooks.router, disruptions.router, plans.router, notifications.router, ai.router, demo.router]
for _router in ROUTERS:
    app.include_router(_router)


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "disruptioniq-api"}
