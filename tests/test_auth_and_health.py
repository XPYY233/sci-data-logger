"""Tests for X-API-Key auth and the deep /health probe.

Both behaviors are critical for production deploy hardening — keep them in a
dedicated module so the relationship to the api_key setting and the DB probe
stays obvious.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from sci_data_logger.schemas import ExperimentRecord


@pytest.fixture
def app_with_temp_db(monkeypatch, tmp_path):
    monkeypatch.setenv("SCI_DATA_LOGGER_STORAGE_ROOT", str(tmp_path))
    monkeypatch.delenv("SCI_DATA_LOGGER_API_KEY", raising=False)
    from sci_data_logger.config import get_settings

    get_settings.cache_clear()
    from sci_data_logger.db.session import reset_engine_cache

    reset_engine_cache()
    from sci_data_logger.main import create_app

    app = create_app()
    yield app
    reset_engine_cache()
    get_settings.cache_clear()


@pytest.fixture
def app_with_api_key(monkeypatch, tmp_path):
    """Like app_with_temp_db but with SCI_DATA_LOGGER_API_KEY set."""
    monkeypatch.setenv("SCI_DATA_LOGGER_STORAGE_ROOT", str(tmp_path))
    monkeypatch.setenv("SCI_DATA_LOGGER_API_KEY", "test-key-do-not-use-in-prod")
    from sci_data_logger.config import get_settings

    get_settings.cache_clear()
    from sci_data_logger.db.session import reset_engine_cache

    reset_engine_cache()
    from sci_data_logger.main import create_app

    app = create_app()
    yield app
    reset_engine_cache()
    get_settings.cache_clear()


# ---------- Auth: open mode (no key configured) ----------

def test_api_endpoints_open_when_no_key_configured(app_with_temp_db):
    """Default dev behavior: API key unset → all endpoints accessible without
    any auth header. This preserves backward-compat with existing test suites
    and local development."""
    client = TestClient(app_with_temp_db)
    # A read endpoint that requires going through the secured router.
    response = client.get("/experiments")
    assert response.status_code == 200
    assert response.json() == []


# ---------- Auth: enforced mode (key configured) ----------

def test_api_endpoint_rejects_missing_key_when_configured(app_with_api_key):
    client = TestClient(app_with_api_key)
    response = client.get("/experiments")
    assert response.status_code == 401
    assert "X-API-Key" in response.json()["detail"]


def test_api_endpoint_rejects_wrong_key_when_configured(app_with_api_key):
    client = TestClient(app_with_api_key)
    response = client.get("/experiments", headers={"X-API-Key": "wrong-value"})
    assert response.status_code == 401


def test_api_endpoint_accepts_correct_key(app_with_api_key):
    client = TestClient(app_with_api_key)
    response = client.get(
        "/experiments",
        headers={"X-API-Key": "test-key-do-not-use-in-prod"},
    )
    assert response.status_code == 200


def test_api_endpoint_rejects_wrong_key_on_mutating_endpoint(app_with_api_key):
    """The PATCH /status endpoint should also enforce. Picking a non-existent
    id verifies that the auth check runs BEFORE the 404 lookup — if the order
    were reversed, an attacker could probe for valid IDs without the key."""
    client = TestClient(app_with_api_key)
    response = client.patch(
        "/experiments/SOME-ID/status",
        json={"status": "reviewed"},
        # No X-API-Key header.
    )
    assert response.status_code == 401, (
        "auth must run before 404; got "
        f"{response.status_code} — that lets unauthenticated clients probe IDs"
    )


def test_health_remains_open_even_with_api_key_configured(app_with_api_key):
    """Health probe (k8s liveness) typically can't add an X-API-Key header.
    Verify /health is reachable without a key even when auth is enforced."""
    client = TestClient(app_with_api_key)
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["api_key_enforced"] is True


# ---------- Health: deep DB probe ----------

def test_health_reports_db_ok_when_db_reachable(app_with_temp_db):
    client = TestClient(app_with_temp_db)
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["database"] == "ok"
    assert "vlm_model" in body
    assert "dashscope_configured" in body
    assert body["api_key_enforced"] is False


def test_health_returns_503_when_db_unreachable(app_with_temp_db, monkeypatch):
    """Simulate a DB outage by patching session.execute to raise. /health
    must return 503 with status=degraded and the database error class name."""

    from sqlalchemy.exc import OperationalError

    # Override the get_session dependency to yield a broken session.
    class _BrokenSession:
        def execute(self, *args, **kwargs):
            raise OperationalError("simulated", None, Exception("db gone"))

        def commit(self):
            pass

        def rollback(self):
            pass

        def close(self):
            pass

    from sci_data_logger.db.session import get_session

    def _broken():
        yield _BrokenSession()

    app_with_temp_db.dependency_overrides[get_session] = _broken
    try:
        client = TestClient(app_with_temp_db)
        response = client.get("/health")
        assert response.status_code == 503
        body = response.json()
        assert body["status"] == "degraded"
        assert body["database"].startswith("error: ")
        # Should mention the exception class name (OperationalError or similar).
        assert "Error" in body["database"]
    finally:
        app_with_temp_db.dependency_overrides.pop(get_session, None)


# ---------- Test record helper for the next round (sanity that
# existing endpoints still work end-to-end through health + auth scaffolding).

def test_full_flow_open_mode_create_get_delete(app_with_temp_db):
    """Smoke: with no API key configured, the full lifecycle still works."""
    from sci_data_logger.db import repository
    from sci_data_logger.db.session import get_engine_cached, get_session_factory

    factory = get_session_factory(get_engine_cached())
    with factory() as session:
        repository.save_record(session, ExperimentRecord(experiment_id="EXP-SMOKE"))
        session.commit()

    client = TestClient(app_with_temp_db)
    assert client.get("/experiments/EXP-SMOKE").status_code == 200
    assert client.delete("/experiments/EXP-SMOKE").status_code == 204
