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


def test_resolve_events_links_local_refs_to_catalog_ids(tmp_path):
    from sci_data_logger.schemas import ExperimentEvent, EventIO, EventOutput

    page1 = PagePacket(source_path="p1.jpg")
    page1.raw_model_output = {"json": {
        "materials_catalog": [
            {"canonical_name": "LiCl", "role": "precursor", "aliases": ["氯化锂"]},
            {"canonical_name": "Li2ZrCl6", "role": "target"},
        ],
        "instruments_catalog": [
            {"technique": "ball_mill", "instrument_label": "707"},
        ],
    }}
    page1.extracted_events = [
        ExperimentEvent(
            sequence_index=1,
            date_label="5.20",
            action_type="mill",
            description="球磨",
            instrument_ref="ball_mill@707",
            inputs=[EventIO(material_ref="LiCl")],
            outputs=[EventOutput(material_ref="氯化锂")],  # alias matching
            page_ref=page1.page_id,
        ),
        ExperimentEvent(
            sequence_index=2,
            action_type="mill",
            description="第二步",
            inputs=[EventIO(material_ref="ZrCl4")],   # not in catalog -> auto add
            outputs=[],
            page_ref=page1.page_id,
        ),
    ]

    img1 = tmp_path / "p1.jpg"; img1.write_bytes(b"x")
    orch = ExperimentOrchestrator(
        document_processor=_FakeDocumentProcessor([page1]),
    )
    record = orch.create_draft(DraftExperimentRequest(
        experiment_id="EXP-EVT", image_paths=[img1],
    ))

    assert len(record.events) == 2
    e1 = record.events[0]
    assert e1.action_type == "mill"
    licl = next(m for m in record.materials_catalog if m.canonical_name == "LiCl")
    assert e1.inputs[0].material_ref == licl.material_id
    assert e1.outputs[0].material_ref == licl.material_id  # alias resolved to LiCl
    instr = next(i for i in record.instruments_catalog if i.instrument_label == "707")
    assert e1.instrument_ref == instr.instrument_id

    assert any(m.canonical_name == "ZrCl4" for m in record.materials_catalog)
    e2 = record.events[1]
    zrcl4 = next(m for m in record.materials_catalog if m.canonical_name == "ZrCl4")
    assert e2.inputs[0].material_ref == zrcl4.material_id

    assert [e.sequence_index for e in record.events] == [1, 2]

    assert any(
        "unresolved" in (i.detail or "").lower() or "ZrCl4" in (i.detail or "")
        for i in record.review_issues
    )
