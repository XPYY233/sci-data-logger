from __future__ import annotations

from pathlib import Path

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


# ----- Gap 1: incremental upload merge -----------------------------------

def _stub_doc_processor_with_materials(monkeypatch, materials_by_filename: dict[str, str]):
    """Stub DocumentProcessor.analyze_page so each uploaded file emits one
    PagePacket declaring exactly one material (selected by filename suffix)."""
    from sci_data_logger.schemas import PagePacket
    from sci_data_logger.services import orchestrator as orch_module

    def fake_analyze_page(self, image_path, prev_tail=None):
        name = Path(image_path).name
        material_name = None
        for key, mat in materials_by_filename.items():
            if name.endswith(key):
                material_name = mat
                break
        if material_name is None:
            material_name = f"AutoMat-{name}"
        return PagePacket(
            source_path=str(image_path),
            page_types=["protocol"],
            raw_model_output={
                "json": {
                    "materials_catalog": [
                        {"canonical_name": material_name, "role": "reactant", "aliases": []}
                    ],
                    "instruments_catalog": [],
                }
            },
        )

    def fake_analyze_pages(self, image_path, prev_tail=None):
        return [fake_analyze_page(self, image_path, prev_tail)]

    monkeypatch.setattr(orch_module.DocumentProcessor, "analyze_page", fake_analyze_page)
    monkeypatch.setattr(orch_module.DocumentProcessor, "analyze_pages", fake_analyze_pages)


def _png_bytes() -> bytes:
    return (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08"
        b"\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc```\x00\x00\x00"
        b"\x04\x00\x01\xa1G\xe9_\x00\x00\x00\x00IEND\xaeB`\x82"
    )


def test_repeat_upload_merges_pages_not_overwrites(monkeypatch, app_with_temp_db):
    _stub_doc_processor_with_materials(
        monkeypatch, {"first.png": "Material-A", "second.png": "Material-B"}
    )
    client = TestClient(app_with_temp_db)

    r1 = client.post(
        "/experiments/draft/upload",
        data={"experiment_id": "EXP-INC"},
        files=[("images", ("first.png", _png_bytes(), "image/png"))],
    )
    assert r1.status_code == 200, r1.text
    assert len(r1.json()["pages"]) == 1

    r2 = client.post(
        "/experiments/draft/upload",
        data={"experiment_id": "EXP-INC"},
        files=[("images", ("second.png", _png_bytes(), "image/png"))],
    )
    assert r2.status_code == 200, r2.text
    rec2 = r2.json()
    assert len(rec2["pages"]) == 2
    names = sorted(m["canonical_name"] for m in rec2["materials_catalog"])
    assert names == ["Material-A", "Material-B"], names


def test_append_pages_endpoint_returns_404_for_unknown_id(app_with_temp_db):
    client = TestClient(app_with_temp_db)
    resp = client.post(
        "/experiments/DOES-NOT-EXIST/pages",
        files=[("images", ("p.png", _png_bytes(), "image/png"))],
    )
    assert resp.status_code == 404


def test_append_pages_endpoint_merges_into_existing_record(monkeypatch, app_with_temp_db):
    _stub_doc_processor_with_materials(
        monkeypatch, {"orig.png": "Material-O", "extra.png": "Material-X"}
    )
    client = TestClient(app_with_temp_db)

    create = client.post(
        "/experiments/draft/upload",
        data={"experiment_id": "EXP-APP"},
        files=[("images", ("orig.png", _png_bytes(), "image/png"))],
    )
    assert create.status_code == 200, create.text

    append = client.post(
        "/experiments/EXP-APP/pages",
        files=[("images", ("extra.png", _png_bytes(), "image/png"))],
    )
    assert append.status_code == 200, append.text
    rec = append.json()
    assert len(rec["pages"]) == 2
    catalog_names = sorted(m["canonical_name"] for m in rec["materials_catalog"])
    assert catalog_names == ["Material-O", "Material-X"], catalog_names


def test_merge_preserves_locked_status(monkeypatch, app_with_temp_db):
    _stub_doc_processor_with_materials(
        monkeypatch, {"a.png": "Mat-1", "b.png": "Mat-2"}
    )
    client = TestClient(app_with_temp_db)

    r = client.post(
        "/experiments/draft/upload",
        data={"experiment_id": "EXP-LOCK"},
        files=[("images", ("a.png", _png_bytes(), "image/png"))],
    )
    assert r.status_code == 200, r.text

    patch = client.patch(
        "/experiments/EXP-LOCK/status",
        json={"status": ReviewStatus.LOCKED.value},
    )
    assert patch.status_code == 200, patch.text
    assert patch.json()["status"] == ReviewStatus.LOCKED.value

    merge = client.post(
        "/experiments/draft/upload",
        data={"experiment_id": "EXP-LOCK"},
        files=[("images", ("b.png", _png_bytes(), "image/png"))],
    )
    assert merge.status_code == 200, merge.text
    merged = merge.json()
    assert merged["status"] == ReviewStatus.LOCKED.value
    assert len(merged["pages"]) == 2
