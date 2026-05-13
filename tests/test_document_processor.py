from pathlib import Path

from sci_data_logger.schemas import DraftExperimentRequest, ReviewStatus
from sci_data_logger.services.document import DocumentProcessor
from sci_data_logger.services.orchestrator import ExperimentOrchestrator
from sci_data_logger.utils.json_tools import parse_first_json_object


class FakeVLMClient:
    def analyze_image(self, image_path: Path, prompt: str) -> dict[str, object]:
        return {
            "raw_text": "not json",
            "json": parse_first_json_object("not json"),
            "model": "fake",
            "usage": None,
        }


class FakePayloadVLMClient:
    """Returns a configurable JSON payload (already parsed) as if VLM produced it."""

    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload

    def analyze_image(self, image_path: Path, prompt: str) -> dict[str, object]:
        return {
            "raw_text": "<mocked>",
            "json": self.payload,
            "model": "fake",
            "usage": None,
        }


def test_vlm_unparseable_json_keeps_review_signals(tmp_path: Path) -> None:
    image_path = tmp_path / "page.jpg"
    image_path.write_bytes(b"fake image")

    page = DocumentProcessor(vlm_client=FakeVLMClient()).analyze_page(image_path)

    assert page.review_required is True
    assert page.warnings
    assert page.open_questions
    assert page.text_blocks == ["not json"]
    assert page.raw_model_output["json"]["_parse_error"] == "no_json_object"


def test_unparseable_page_marks_experiment_needs_review(tmp_path: Path) -> None:
    image_path = tmp_path / "page.jpg"
    image_path.write_bytes(b"fake image")

    orchestrator = ExperimentOrchestrator(
        document_processor=DocumentProcessor(vlm_client=FakeVLMClient())
    )
    record = orchestrator.create_draft(
        DraftExperimentRequest(experiment_id="EXP-REVIEW-001", image_paths=[image_path])
    )

    assert record.status == ReviewStatus.NEEDS_REVIEW
    assert record.review_issues


def test_vlm_structured_payload_populates_record(tmp_path: Path) -> None:
    payload = {
        "page_type": ["synthesis_note"],
        "sample_id": "Na4Mn9O18-batch3",
        "materials": [
            {
                "name": "Mn2O3",
                "role": "precursor",
                "amount": {"value": 1.5787, "unit": "g", "confidence": 0.9},
            },
            {
                "name": "Na2CO3",
                "role": "precursor",
                "amount": {"value": 0.499, "unit": "g", "confidence": 0.8},
            },
            {"name": "Na4Mn9O18", "role": "target", "amount": None},
        ],
        "steps": [
            {
                "step_type": "weigh",
                "sequence_index": 2,
                "description": "称量原料",
                "confidence": 0.85,
            },
            {
                "step_type": "calcine",
                "sequence_index": 1,
                "description": "500°C 预烧 6h",
                "parameters": {
                    "temperature": {"value": 500, "unit": "C", "confidence": 0.9},
                    "duration": {"value": 6, "unit": "h", "confidence": 0.9},
                },
                "confidence": 0.85,
            },
        ],
        "observations": [
            {"value": "850°C 含 Mn2O3 杂质", "unit": None, "confidence": 0.9}
        ],
        "instruments": ["707炉"],
        "text_blocks": ["9.18 合 Na4Mn9O18"],
        "table_blocks": [],
        "extracted_facts": {},
        "open_questions": [],
        "warnings": [],
        "review_required": False,
    }
    image_path = tmp_path / "page.jpg"
    image_path.write_bytes(b"fake image")

    record = ExperimentOrchestrator(
        document_processor=DocumentProcessor(vlm_client=FakePayloadVLMClient(payload))
    ).create_draft(
        DraftExperimentRequest(experiment_id="EXP-FULL-001", image_paths=[image_path])
    )

    assert len(record.materials) == 3
    names = {m.name for m in record.materials}
    assert names == {"Mn2O3", "Na2CO3", "Na4Mn9O18"}
    assert len(record.steps) == 2
    assert [s.sequence_index for s in record.steps] == [1, 2]
    # sorted by sequence_index in payload (1, 2): calcine first, then weigh
    assert record.steps[0].step_type == "calcine"
    assert record.steps[1].step_type == "weigh"
    assert len(record.observations) == 1
    assert record.pages[0].page_types == ["synthesis_note"]
    assert record.pages[0].sample_id == "Na4Mn9O18-batch3"
    assert record.pages[0].extracted_instruments == ["707炉"]


def test_review_required_triggered_by_low_confidence(tmp_path: Path) -> None:
    payload = {
        "page_type": ["synthesis_note"],
        "materials": [
            {
                "name": "FooX",
                "role": "precursor",
                "amount": {"value": 1.0, "unit": "g", "confidence": 0.5},
            }
        ],
        "steps": [],
        "observations": [],
        "instruments": [],
        "text_blocks": [],
        "table_blocks": [],
        "extracted_facts": {},
        "open_questions": [],
        "warnings": [],
        "review_required": False,
    }
    image_path = tmp_path / "page.jpg"
    image_path.write_bytes(b"fake image")

    page = DocumentProcessor(vlm_client=FakePayloadVLMClient(payload)).analyze_page(image_path)
    assert page.review_required is True


def test_review_required_triggered_by_open_questions(tmp_path: Path) -> None:
    payload = {
        "page_type": ["synthesis_note"],
        "materials": [],
        "steps": [],
        "observations": [],
        "instruments": [],
        "text_blocks": [],
        "table_blocks": [],
        "extracted_facts": {},
        "open_questions": ["这里到底是 500 还是 900？"],
        "warnings": [],
        "review_required": False,
    }
    image_path = tmp_path / "page.jpg"
    image_path.write_bytes(b"fake image")

    page = DocumentProcessor(vlm_client=FakePayloadVLMClient(payload)).analyze_page(image_path)
    assert page.review_required is True


def test_table_blocks_rows_normalized_from_dict(tmp_path: Path) -> None:
    payload = {
        "page_type": ["synthesis_note"],
        "materials": [],
        "steps": [],
        "observations": [],
        "instruments": [],
        "text_blocks": [],
        "table_blocks": [
            {"title": "便利贴", "rows": [{"a": "x", "b": "y"}, {"a": "z", "b": "w"}]}
        ],
        "extracted_facts": {},
        "open_questions": [],
        "warnings": [],
        "review_required": False,
    }
    image_path = tmp_path / "page.jpg"
    image_path.write_bytes(b"fake image")

    page = DocumentProcessor(vlm_client=FakePayloadVLMClient(payload)).analyze_page(image_path)
    tbl = page.table_blocks[0]
    assert tbl["rows"] == [["a", "b"], ["x", "y"], ["z", "w"]]


def test_materials_merged_across_pages(tmp_path: Path) -> None:
    payload = {
        "page_type": ["synthesis_note"],
        "materials": [
            {
                "name": "Mn2O3",
                "role": "precursor",
                "amount": {"value": 1.0, "unit": "g", "confidence": 0.9},
            }
        ],
        "steps": [],
        "observations": [],
        "instruments": [],
        "text_blocks": [],
        "table_blocks": [],
        "extracted_facts": {},
        "open_questions": [],
        "warnings": [],
        "review_required": False,
    }
    image_a = tmp_path / "a.jpg"
    image_a.write_bytes(b"fake image")
    image_b = tmp_path / "b.jpg"
    image_b.write_bytes(b"fake image")

    record = ExperimentOrchestrator(
        document_processor=DocumentProcessor(vlm_client=FakePayloadVLMClient(payload))
    ).create_draft(
        DraftExperimentRequest(experiment_id="EXP-MERGE-001", image_paths=[image_a, image_b])
    )

    # Same (name, role) across two pages -> deduped
    assert len(record.materials) == 1
    assert record.materials[0].name == "Mn2O3"


def test_step_type_aliased_from_chinese(tmp_path: Path) -> None:
    payload = {
        "page_type": ["synthesis_note"],
        "materials": [],
        "steps": [
            {
                "step_type": "煅烧",
                "sequence_index": 1,
                "description": "500°C 煅烧 6h",
                "confidence": 0.9,
            }
        ],
        "observations": [],
        "instruments": [],
        "text_blocks": [],
        "table_blocks": [],
        "extracted_facts": {},
        "open_questions": [],
        "warnings": [],
        "review_required": False,
    }
    image_path = tmp_path / "page.jpg"
    image_path.write_bytes(b"fake image")

    page = DocumentProcessor(vlm_client=FakePayloadVLMClient(payload)).analyze_page(image_path)
    assert len(page.extracted_steps) == 1
    assert page.extracted_steps[0].step_type == "calcine"
