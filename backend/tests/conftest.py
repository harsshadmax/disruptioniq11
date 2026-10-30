"""Test setup: a dedicated Postgres database, migrated with Alembic once per session.

Each test runs inside an outer transaction that is rolled back afterwards (the session uses
savepoints, so app code can call commit()). DB-backed tests need `docker compose up -d db`.
"""
import os
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

BACKEND_DIR = Path(__file__).resolve().parent.parent
TEST_DB = "disruptioniq_test"

_base = make_url(
    os.environ.get("DATABASE_URL", "postgresql+psycopg://disruptioniq:disruptioniq@localhost:5433/disruptioniq")
)
_test_url = _base.set(database=TEST_DB)
os.environ["DATABASE_URL"] = _test_url.render_as_string(hide_password=False)  # before app.config is imported
os.environ.setdefault("JWT_SECRET", "test-secret-test-secret-test-secret-32b")


def _ensure_database() -> None:
    import psycopg

    with psycopg.connect(
        host=_base.host, port=_base.port, user=_base.username, password=_base.password,
        dbname="postgres", autocommit=True, connect_timeout=5,
    ) as conn:
        if not conn.execute("SELECT 1 FROM pg_database WHERE datname = %s", (TEST_DB,)).fetchone():
            conn.execute(f'CREATE DATABASE "{TEST_DB}"')


@pytest.fixture(scope="session")
def migrated_engine():
    try:
        _ensure_database()
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"Postgres not reachable ({exc.__class__.__name__}); run `docker compose up -d db`")
    from alembic import command
    from alembic.config import Config

    engine = create_engine(_test_url)
    with engine.begin() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    command.upgrade(cfg, "head")
    yield engine
    engine.dispose()


@pytest.fixture
def db(migrated_engine):
    conn = migrated_engine.connect()
    outer = conn.begin()
    session = Session(bind=conn, join_transaction_mode="create_savepoint", expire_on_commit=False)
    yield session
    session.close()
    outer.rollback()
    conn.close()


@pytest.fixture
def users(db):
    from app.seed_users import seed_users

    return seed_users(db, password="Test-pass-123", iterations=1000)


@pytest.fixture
def client(db):
    from fastapi.testclient import TestClient

    from app.db import get_db
    from app.main import app

    app.dependency_overrides[get_db] = lambda: db
    yield TestClient(app)
    app.dependency_overrides.clear()


def auth_headers(user) -> dict:
    from app.auth.security import create_access_token

    return {"Authorization": f"Bearer {create_access_token(user.id, user.role)}"}


@pytest.fixture(autouse=True)
def _fresh_login_throttle():
    from app.auth import throttle

    throttle.reset_all()


@pytest.fixture(autouse=True)
def _no_real_ai_calls(monkeypatch):
    """Tests never reach the Anthropic API, whatever the developer has in .env."""
    from app.config import settings

    monkeypatch.setattr(settings, "anthropic_api_key", None)
