from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from sci_data_logger.schemas import (
    ExperimentRecord,
    ReviewIssue,
    ReviewStatus,
)


@pytest.fixture
def app_with_temp_db(monkeypatch, tmp_path):
    monkeypatch.setenv("SCI_DATA_LOGGER_STORAGE_ROOT", str(tmp_path))
    from sci_data_logger.config import get_settings

    get_settings.cache_clear()
    from sci_data_logger.db.session import reset_engine_cache

    reset_engine_cache()
    from sci_data_logger.main import create_app

    app = create_app()
    yield app
    # Tidy up the cache so other tests start clean.
    reset_engine_cache()
    get_settings.cache_clear()


def _stub_vlm_payload(*_args, **_kwargs):
    return {
        "json": {
            "page_type": "experiment_record",
            "sample_id": "S-1",
            "text_blocks": ["stub page"],
            "materials": [],
            "steps": [],
            "observations": [],
            "instruments": [],
            "events": [],
            "warnings": [],
            "open_questions": [],
            "review_required": False,
        }
    }


def _post_draft(client: TestClient, experiment_id: str, **fields) -> dict:
    form = {"experiment_id": experiment_id}
    form.update({k: v for k, v in fields.items() if v is not None})
    response = client.post("/experiments/draft", json={"experiment_id": experiment_id, **fields})
    return response.json()


def test_draft_upload_persists_record_and_get_returns_it(monkeypatch, app_with_temp_db, tmp_path):
    from sci_data_logger.services import document as document_module

    monkeypatch.setattr(
        document_module.QwenVLMClient, "analyze_image", _stub_vlm_payload, raising=True
    )

    client = TestClient(app_with_temp_db)

    image_bytes = b"\x89PNG\r\n\x1a\nfakepngdata"
    response = client.post(
        "/experiments/draft/upload",
        data={"experiment_id": "EXP-001"},
        files=[("images", ("page1.png", image_bytes, "image/png"))],
    )
    assert response.status_code == 200, response.text
    created = response.json()
    assert created["experiment_id"] == "EXP-001"

    fetched = client.get("/experiments/EXP-001")
    assert fetched.status_code == 200
    assert fetched.json()["experiment_id"] == "EXP-001"


def test_list_experiments_filters_by_status(app_with_temp_db):
    from sci_data_logger.db import repository
    from sci_data_logger.db.session import get_engine_cached, get_session_factory

    factory = get_session_factory(get_engine_cached())
    with factory() as session:
        repository.save_record(session, ExperimentRecord(experiment_id="A", status=ReviewStatus.DRAFT))
        repository.save_record(
            session, ExperimentRecord(experiment_id="B", status=ReviewStatus.NEEDS_REVIEW)
        )
        repository.save_record(session, ExperimentRecord(experiment_id="C", status=ReviewStatus.DRAFT))
        session.commit()

    client = TestClient(app_with_temp_db)
    response = client.get("/experiments", params={"status": "draft"})
    assert response.status_code == 200
    ids = sorted(item["experiment_id"] for item in response.json())
    assert ids == ["A", "C"]

    response_all = client.get("/experiments")
    assert response_all.status_code == 200
    assert len(response_all.json()) == 3


def test_patch_status_updates_and_locks_after_review(app_with_temp_db):
    from sci_data_logger.db import repository
    from sci_data_logger.db.session import get_engine_cached, get_session_factory

    factory = get_session_factory(get_engine_cached())
    with factory() as session:
        repository.save_record(session, ExperimentRecord(experiment_id="E1"))
        session.commit()

    client = TestClient(app_with_temp_db)

    response = client.patch("/experiments/E1/status", json={"status": "reviewed"})
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "reviewed"

    fetched = client.get("/experiments/E1")
    assert fetched.json()["status"] == "reviewed"

    response = client.patch("/experiments/E1/status", json={"status": "locked"})
    assert response.status_code == 200
    assert response.json()["status"] == "locked"

    fetched = client.get("/experiments/E1")
    assert fetched.json()["status"] == "locked"


def test_resolve_review_issue_removes_it(app_with_temp_db):
    from sci_data_logger.db import repository
    from sci_data_logger.db.session import get_engine_cached, get_session_factory

    issue = ReviewIssue(title="missing date", detail="page 1 has no date")
    issue_id = issue.issue_id
    record = ExperimentRecord(
        experiment_id="E2",
        review_issues=[issue, ReviewIssue(title="other", detail="x")],
    )

    factory = get_session_factory(get_engine_cached())
    with factory() as session:
        repository.save_record(session, record)
        session.commit()

    client = TestClient(app_with_temp_db)
    response = client.post(f"/experiments/E2/review-issues/{issue_id}/resolve")
    assert response.status_code == 200, response.text
    body = response.json()
    assert len(body["review_issues"]) == 1
    assert all(ri["issue_id"] != issue_id for ri in body["review_issues"])


def test_delete_experiment_returns_204_and_subsequent_get_is_404(app_with_temp_db):
    from sci_data_logger.db import repository
    from sci_data_logger.db.session import get_engine_cached, get_session_factory

    factory = get_session_factory(get_engine_cached())
    with factory() as session:
        repository.save_record(session, ExperimentRecord(experiment_id="DEL-1"))
        session.commit()

    client = TestClient(app_with_temp_db)
    delete_response = client.delete("/experiments/DEL-1")
    assert delete_response.status_code == 204

    get_response = client.get("/experiments/DEL-1")
    assert get_response.status_code == 404

    second_delete = client.delete("/experiments/DEL-1")
    assert second_delete.status_code == 404
