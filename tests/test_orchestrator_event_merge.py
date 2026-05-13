from pathlib import Path

from sci_data_logger.schemas import (
    DraftExperimentRequest,
    Material,
    PagePacket,
)
from sci_data_logger.services.orchestrator import ExperimentOrchestrator


class _FakeDocumentProcessor:
    """Injects pre-constructed PagePacket list."""
    def __init__(self, pages):
        self._pages = list(pages)

    def analyze_page(self, path):
        return self._pages.pop(0)


def test_merge_materials_catalog_deduplicates_across_pages(tmp_path):
    page1 = PagePacket(source_path="p1.jpg")
    page1.raw_model_output = {"json": {"materials_catalog": [
        {"canonical_name": "LiCl", "role": "precursor", "aliases": []},
        {"canonical_name": "ZrCl4", "role": "precursor"},
    ]}}
    page2 = PagePacket(source_path="p2.jpg")
    page2.raw_model_output = {"json": {"materials_catalog": [
        {"canonical_name": "LiCl", "role": "precursor"},  # dup
        {"canonical_name": "Li2ZrCl6", "role": "target"},
    ]}}

    img1 = tmp_path / "p1.jpg"; img1.write_bytes(b"x")
    img2 = tmp_path / "p2.jpg"; img2.write_bytes(b"x")
    orch = ExperimentOrchestrator(
        document_processor=_FakeDocumentProcessor([page1, page2]),
    )
    record = orch.create_draft(DraftExperimentRequest(
        experiment_id="EXP-MERGE", image_paths=[img1, img2],
    ))
    names = sorted(m.canonical_name for m in record.materials_catalog)
    assert names == ["Li2ZrCl6", "LiCl", "ZrCl4"]
    assert sum(1 for m in record.materials_catalog if m.canonical_name == "LiCl") == 1


def test_merge_instruments_catalog_dedup_by_technique_and_label(tmp_path):
    page1 = PagePacket(source_path="p1.jpg")
    page1.raw_model_output = {"json": {"instruments_catalog": [
        {"technique": "ball_mill", "instrument_label": "707", "model": "高能行星"},
    ]}}
    page2 = PagePacket(source_path="p2.jpg")
    page2.raw_model_output = {"json": {"instruments_catalog": [
        {"technique": "ball_mill", "instrument_label": "707"},  # dup
        {"technique": "ball_mill", "instrument_label": None, "model": "其他"},
    ]}}

    img1 = tmp_path / "p1.jpg"; img1.write_bytes(b"x")
    img2 = tmp_path / "p2.jpg"; img2.write_bytes(b"x")
    orch = ExperimentOrchestrator(
        document_processor=_FakeDocumentProcessor([page1, page2]),
    )
    record = orch.create_draft(DraftExperimentRequest(
        experiment_id="EXP-INSTR", image_paths=[img1, img2],
    ))
    # 707 一份，无 label 一份，共 2 条
    assert len(record.instruments_catalog) == 2
    labels = sorted([ins.instrument_label for ins in record.instruments_catalog],
                    key=lambda x: (x is None, x))
    assert labels == ["707", None]
