
from sci_data_logger.schemas import (
    DraftExperimentRequest,
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

    img1 = tmp_path / "p1.jpg"
    img1.write_bytes(b"x")
    img2 = tmp_path / "p2.jpg"
    img2.write_bytes(b"x")
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

    img1 = tmp_path / "p1.jpg"
    img1.write_bytes(b"x")
    img2 = tmp_path / "p2.jpg"
    img2.write_bytes(b"x")
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

    img1 = tmp_path / "p1.jpg"
    img1.write_bytes(b"x")
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


def test_global_event_sort_prefers_page_number_hint_over_upload_order(tmp_path):
    from sci_data_logger.schemas import ExperimentEvent

    # page_B is uploaded first but has hint=2; page_A is uploaded second with hint=1.
    # Neither event has date_iso. Events from page_A must sort before events from page_B.
    page_b = PagePacket(source_path="b.jpg", page_number_hint=2)
    page_b.extracted_events = [
        ExperimentEvent(
            sequence_index=1,
            action_type="mill",
            description="from-page-B",
            page_ref=page_b.page_id,
        ),
    ]
    page_a = PagePacket(source_path="a.jpg", page_number_hint=1)
    page_a.extracted_events = [
        ExperimentEvent(
            sequence_index=1,
            action_type="weigh",
            description="from-page-A",
            page_ref=page_a.page_id,
        ),
    ]

    img_b = tmp_path / "b.jpg"
    img_b.write_bytes(b"x")
    img_a = tmp_path / "a.jpg"
    img_a.write_bytes(b"x")
    orch = ExperimentOrchestrator(
        document_processor=_FakeDocumentProcessor([page_b, page_a]),
    )
    record = orch.create_draft(DraftExperimentRequest(
        experiment_id="EXP-SORT", image_paths=[img_b, img_a],
    ))

    assert len(record.events) == 2
    descriptions = [e.description for e in record.events]
    assert descriptions == ["from-page-A", "from-page-B"]


def test_end_to_end_event_centric_record_from_mock_vlm(tmp_path, monkeypatch):
    """完整路径：mock VLM → DocumentProcessor → Orchestrator → ExperimentRecord."""
    from sci_data_logger.services.document import DocumentProcessor
    from sci_data_logger.vlm import QwenVLMClient

    class FakeVLMClient(QwenVLMClient):
        def __init__(self): pass
        def analyze_image(self, image_path, prompt):
            return {
                "raw_text": "...",
                "json": {
                    "page_types": ["synthesis_note", "calculation"],
                    "sample_id": "Li2ZrCl6",
                    "materials_catalog": [
                        {"canonical_name": "LiCl", "role": "precursor"},
                        {"canonical_name": "ZrCl4", "role": "precursor"},
                        {"canonical_name": "Li2ZrCl6", "role": "target"},
                    ],
                    "instruments_catalog": [
                        {"technique": "ball_mill", "instrument_label": "707",
                         "model": "高能行星球磨"},
                    ],
                    "events": [
                        {
                            "sequence_index": 1,
                            "date_label": "5.20",
                            "action_type": "mill",
                            "description": "600rpm 15h",
                            "instrument_ref_local": "ball_mill@707",
                            "inputs": [{"material_ref_local": "LiCl"},
                                       {"material_ref_local": "ZrCl4"}],
                            "outputs": [{"material_ref_local": "Li2ZrCl6",
                                         "failure_marker": "没合成"}],
                            "parameters": {"speed": {"value": 600, "unit": "rpm"}},
                            "equation": "2LiCl + ZrCl4 = Li2ZrCl6",
                            "confidence": 0.9,
                        }
                    ],
                    "extracted_dates": ["5.20"],
                    "extracted_target_phases": ["P-3m1"],
                    "extracted_failure_markers": [{"marker": "X", "target": "Li2ZrCl6"}],
                    "text_blocks": [],
                    "table_blocks": [],
                    "open_questions": [],
                    "warnings": [],
                    "review_required": True,
                },
                "model": "qwen3.6-plus",
                "usage": None,
            }

    img = tmp_path / "fake.jpg"
    img.write_bytes(b"x")
    dp = DocumentProcessor(vlm_client=FakeVLMClient())
    orch = ExperimentOrchestrator(document_processor=dp)
    record = orch.create_draft(DraftExperimentRequest(
        experiment_id="E2E-EVENT", image_paths=[img],
    ))

    # Top-level catalogs
    assert {m.canonical_name for m in record.materials_catalog} == {"LiCl", "ZrCl4", "Li2ZrCl6"}
    assert len(record.instruments_catalog) == 1
    assert record.instruments_catalog[0].instrument_label == "707"

    # Events resolved
    assert len(record.events) == 1
    e = record.events[0]
    assert e.action_type == "mill"
    assert e.date_iso == "2026-05-20"
    assert e.equation == "2LiCl + ZrCl4 = Li2ZrCl6"
    licl_id = next(m for m in record.materials_catalog if m.canonical_name == "LiCl").material_id
    assert e.inputs[0].material_ref == licl_id
    instr_id = record.instruments_catalog[0].instrument_id
    assert e.instrument_ref == instr_id

    # Compat properties
    assert len(record.materials) == 3
    assert len(record.steps) == 1
    assert record.steps[0].step_type == "mill"

    # PagePacket new fields populated
    assert "5.20" in record.pages[0].extracted_dates
    assert "P-3m1" in record.pages[0].extracted_target_phases

    # Status
    assert record.status.value == "needs_review"
