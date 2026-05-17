"""End-to-end verification of the SciDataLoggerError → HTTP response pipeline.

For each domain exception we care about:
- raise it from a real production code path (or stub the trigger)
- send a request through TestClient
- assert (a) HTTP status from `http_status`, (b) JSON body shape
  `{"error": {"type": "<ClassName>", "detail": "...", "retryable": bool}}`,
  (c) Retry-After header present iff retryable=True.

This is the load-bearing test for Option A — without it, a future refactor
that drops the global handler registration would silently regress the API
contract.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from sci_data_logger.errors import (
    CorruptRecordError,
    VLMAuthenticationError,
    VLMBadRequestError,
    VLMGlobalConcurrencyTimeout,
    VLMNotConfiguredError,
    VLMTransientError,
)


@pytest.fixture
def app(monkeypatch, tmp_path):
    monkeypatch.setenv("SCI_DATA_LOGGER_STORAGE_ROOT", str(tmp_path))
    monkeypatch.delenv("SCI_DATA_LOGGER_API_KEY", raising=False)
    from sci_data_logger.config import get_settings

    get_settings.cache_clear()
    from sci_data_logger.db.session import reset_engine_cache

    reset_engine_cache()
    from sci_data_logger.main import create_app

    yield create_app()
    reset_engine_cache()
    get_settings.cache_clear()


def _png_bytes() -> bytes:
    return (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08"
        b"\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc```\x00\x00\x00"
        b"\x04\x00\x01\xa1G\xe9_\x00\x00\x00\x00IEND\xaeB`\x82"
    )


def _post_upload_that_raises(app, monkeypatch, exc_to_raise: Exception):
    """Helper: install a fake DocumentProcessor that raises `exc_to_raise`
    out of analyze_pages, then POST a one-file upload."""
    from sci_data_logger.services import orchestrator as orch_module

    def fake_analyze_pages(self, source_path, prev_tail=None):
        raise exc_to_raise

    monkeypatch.setattr(
        orch_module.DocumentProcessor, "analyze_pages", fake_analyze_pages
    )
    monkeypatch.setattr(
        orch_module.DocumentProcessor, "analyze_page", fake_analyze_pages
    )

    client = TestClient(app, raise_server_exceptions=False)
    return client.post(
        "/experiments/draft/upload",
        data={"experiment_id": "EXP-DOMAIN"},
        files=[("images", ("p.png", _png_bytes(), "image/png"))],
    )


# ---------- Per-exception HTTP mapping ----------

def test_vlm_not_configured_returns_503(app, monkeypatch):
    """VLMNotConfiguredError is a ConfigurationError → 503, not retryable."""
    response = _post_upload_that_raises(
        app,
        monkeypatch,
        VLMNotConfiguredError("DASHSCOPE_API_KEY is not configured."),
    )
    assert response.status_code == 503
    body = response.json()
    assert body["error"]["type"] == "VLMNotConfiguredError"
    assert "not configured" in body["error"]["detail"]
    assert body["error"]["retryable"] is False
    assert "Retry-After" not in response.headers


def test_vlm_authentication_error_returns_502(app, monkeypatch):
    response = _post_upload_that_raises(
        app, monkeypatch, VLMAuthenticationError("DashScope rejected the key")
    )
    assert response.status_code == 502
    body = response.json()
    assert body["error"]["type"] == "VLMAuthenticationError"
    assert body["error"]["retryable"] is False


def test_vlm_bad_request_returns_502(app, monkeypatch):
    response = _post_upload_that_raises(
        app, monkeypatch, VLMBadRequestError("upstream rejected: model bad")
    )
    assert response.status_code == 502
    body = response.json()
    assert body["error"]["type"] == "VLMBadRequestError"
    assert body["error"]["retryable"] is False


def test_vlm_transient_error_returns_503_with_retry_after(app, monkeypatch):
    """Transient errors (retries exhausted) are retryable → 503 + Retry-After."""
    response = _post_upload_that_raises(
        app, monkeypatch, VLMTransientError("rate limited after 3 retries")
    )
    assert response.status_code == 503
    body = response.json()
    assert body["error"]["type"] == "VLMTransientError"
    assert body["error"]["retryable"] is True
    assert response.headers.get("Retry-After") == "60"


def test_vlm_global_concurrency_timeout_returns_503_with_retry_after(app, monkeypatch):
    """Global semaphore timeout is also retryable."""
    response = _post_upload_that_raises(
        app, monkeypatch, VLMGlobalConcurrencyTimeout("sem acquire timeout")
    )
    assert response.status_code == 503
    body = response.json()
    assert body["error"]["type"] == "VLMGlobalConcurrencyTimeout"
    assert body["error"]["retryable"] is True
    assert response.headers.get("Retry-After") == "60"


def test_corrupt_record_returns_500_typed(app, monkeypatch):
    """Hand-write a malformed JSON blob into the DB then GET it.

    Verifies that the read-path translation in repository._load_record
    surfaces CorruptRecordError instead of leaking pydantic.ValidationError
    to the client.
    """
    from sci_data_logger.db.models import ExperimentRecordORM
    from sci_data_logger.db.session import get_engine_cached, get_session_factory

    factory = get_session_factory(get_engine_cached())
    with factory() as session:
        session.add(
            ExperimentRecordORM(
                experiment_id="EXP-CORRUPT",
                status="draft",
                record_json='{"this_is_not_a_valid_ExperimentRecord": true}',
            )
        )
        session.commit()

    client = TestClient(app, raise_server_exceptions=False)
    response = client.get("/experiments/EXP-CORRUPT")
    assert response.status_code == 500
    body = response.json()
    assert body["error"]["type"] == "CorruptRecordError"
    assert "EXP-CORRUPT" in body["error"]["detail"]
    assert body["error"]["retryable"] is False
    assert "Retry-After" not in response.headers


# ---------- Exception class invariants ----------

def test_all_domain_exceptions_have_http_status():
    """Every concrete SciDataLoggerError subclass must declare an http_status
    in 4xx-5xx. Without this, the global handler would emit a default that
    surprises clients."""
    from sci_data_logger.errors import SciDataLoggerError

    def walk(cls):
        for sub in cls.__subclasses__():
            yield sub
            yield from walk(sub)

    leaves = [c for c in walk(SciDataLoggerError) if not c.__subclasses__()]
    assert leaves, "expected at least one concrete subclass"
    for cls in leaves:
        assert 400 <= cls.http_status < 600, (
            f"{cls.__name__}.http_status = {cls.http_status}; must be 4xx or 5xx"
        )
        assert isinstance(cls.retryable, bool)


def test_corrupt_record_keeps_cause():
    """The wrapped ValidationError stays as __cause__ for debugging."""
    try:
        raise ValueError("simulated pydantic failure")
    except ValueError as exc:
        err = CorruptRecordError("EXP-X", cause=exc)
    assert err.experiment_id == "EXP-X"
    assert isinstance(err.__cause__, ValueError)


def test_corrupt_record_triggers_on_malformed_json(app):
    """Reviewer follow-up: lock in that pydantic-v2's ValidationError covers
    BOTH well-formed-wrong-shape AND literal malformed JSON. Without this,
    a future pydantic version that splits the JSON-decode error out of
    ValidationError would silently regress `_load_record`'s catch."""
    from sci_data_logger.db.models import ExperimentRecordORM
    from sci_data_logger.db.session import get_engine_cached, get_session_factory

    factory = get_session_factory(get_engine_cached())
    with factory() as session:
        session.add(
            ExperimentRecordORM(
                experiment_id="EXP-BAD-JSON",
                status="draft",
                # Literally invalid JSON — unterminated object, trailing comma.
                record_json='{"experiment_id": "EXP-BAD-JSON", "pages": [,',
            )
        )
        session.commit()

    client = TestClient(app, raise_server_exceptions=False)
    response = client.get("/experiments/EXP-BAD-JSON")
    assert response.status_code == 500
    body = response.json()
    assert body["error"]["type"] == "CorruptRecordError"
    assert "EXP-BAD-JSON" in body["error"]["detail"]
