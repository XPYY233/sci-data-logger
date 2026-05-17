from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from extensions.personalization.service import save_user_profile
from extensions.workbench import api as workbench_api
from extensions.workbench.app import create_workbench_app


def _sample_record() -> dict:
    return {
        "experiment_id": "EXP-DEMO-001",
        "operator": "alice",
        "pages": [
            {
                "sample_id": "S2026001",
                "extracted_materials": [{"name": "Mn2O3"}],
                "extracted_steps": [{"step_type": "预烧", "description": "500°C 预烧"}],
                "extracted_facts": {"temperature": {"value": 500, "unit": "C"}},
            }
        ],
    }


def _configure_paths(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(workbench_api, "DEFAULT_LOCAL_ROOT", tmp_path)
    monkeypatch.setattr(workbench_api, "DEFAULT_DB_PATH", tmp_path / "personalization.db")


def test_workbench_keeps_core_health_route_available() -> None:
    client = TestClient(create_workbench_app())

    response = client.get("/health")

    assert response.status_code == 200


def test_workbench_user_api_supports_crud(monkeypatch, tmp_path: Path) -> None:
    _configure_paths(monkeypatch, tmp_path)
    client = TestClient(create_workbench_app())

    create = client.put(
        "/workbench/api/users/alice",
        json={
            "display_name": "Alice",
            "term_aliases": {"预烧": "calcine"},
            "sample_id_patterns": ["A-{seq}"],
            "preferred_fields": ["duration"],
            "required_fields": ["temperature"],
            "handwriting_notes": [],
        },
    )
    listed = client.get("/workbench/api/users")
    fetched = client.get("/workbench/api/users/alice")

    assert create.status_code == 200
    assert listed.status_code == 200
    assert listed.json()[0]["user_id"] == "alice"
    assert fetched.json()["term_aliases"]["预烧"] == "calcine"


def test_workbench_user_api_rejects_unapproved_fields(monkeypatch, tmp_path: Path) -> None:
    _configure_paths(monkeypatch, tmp_path)
    client = TestClient(create_workbench_app())

    response = client.put(
        "/workbench/api/users/alice",
        json={"display_name": "Alice", "instrument_id": "xrd"},
    )

    assert response.status_code == 422


def test_workbench_templates_and_personalized_analysis(monkeypatch, tmp_path: Path) -> None:
    _configure_paths(monkeypatch, tmp_path)
    save_user_profile(
        "alice",
        {
            "display_name": "Alice",
            "term_aliases": {"一烧": "calcine_stage_1"},
            "required_fields": ["duration"],
        },
        local_root=tmp_path,
        db_path=tmp_path / "personalization.db",
    )
    client = TestClient(create_workbench_app())

    templates = client.get("/workbench/api/templates")
    analysis = client.post(
        "/workbench/api/personalized-analysis",
        json={
            "record": _sample_record(),
            "user_id": "alice",
            "experiment_template_id": "solid_state_synthesis",
            "instrument_id": "generic_xrd",
            "group_id": "materials_default",
        },
    )

    assert templates.status_code == 200
    assert any(item["id"] == "solid_state_synthesis" for item in templates.json()["experiments"])
    assert analysis.status_code == 200
    payload = analysis.json()
    assert {"raw_step_type": "预烧", "normalized_step_type": "calcine", "description": "500°C 预烧"} in payload[
        "normalized_step_changes"
    ]
    assert "duration" in payload["missing_required_fields"]
