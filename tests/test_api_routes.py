from pathlib import Path

from fastapi.testclient import TestClient

from sci_data_logger.api import routes
from sci_data_logger.config import Settings
from sci_data_logger.main import create_app
from sci_data_logger.schemas import DraftExperimentRequest, ExperimentRecord


def test_json_draft_rejects_server_local_paths() -> None:
    client = TestClient(create_app())

    response = client.post(
        "/experiments/draft",
        json={"experiment_id": "EXP-001", "image_paths": ["/etc/passwd"]},
    )

    assert response.status_code == 422


def test_upload_draft_saves_files_under_storage_root(monkeypatch, tmp_path: Path) -> None:
    captured: dict[str, DraftExperimentRequest] = {}

    class FakeOrchestrator:
        def create_draft(self, request: DraftExperimentRequest) -> ExperimentRecord:
            captured["request"] = request
            return ExperimentRecord(experiment_id=request.experiment_id)

    monkeypatch.setattr(routes, "get_settings", lambda: Settings(storage_root=tmp_path))
    monkeypatch.setattr(routes, "ExperimentOrchestrator", lambda: FakeOrchestrator())
    client = TestClient(create_app())

    response = client.post(
        "/experiments/draft/upload",
        data={"experiment_id": "../EXP 001", "user_fields": '{"sample_id": "S-1"}'},
        files=[
            (
                "instrument_files",
                ("../unsafe.csv", b"angle,intensity\n10,100\n", "text/csv"),
            )
        ],
    )

    assert response.status_code == 200
    request = captured["request"]
    saved_path = request.instrument_file_paths[0]
    assert saved_path.is_relative_to(tmp_path.resolve())
    assert saved_path.read_text(encoding="utf-8") == "angle,intensity\n10,100\n"
    assert ".." not in saved_path.name
    assert saved_path.name.endswith("_unsafe.csv")
    assert request.image_paths == []
    assert request.user_fields == {"sample_id": "S-1"}


def test_runtime_config_does_not_expose_local_paths(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(routes, "get_settings", lambda: Settings(storage_root=tmp_path))
    client = TestClient(create_app())

    response = client.get("/runtime/config")

    assert response.status_code == 200
    payload = response.json()
    assert "storage_root" not in payload
    assert "instrument_registry" not in payload
    assert "group_template" not in payload
