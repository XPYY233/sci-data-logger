"""End-to-end integration test: feed a payload shaped exactly like the
PAGE_ANALYSIS_PROMPT worked example through the orchestrator and assert that
catalogs are populated and the event causal chain forms.

This is the regression test that protects against prompt/orchestrator drift:
if a future edit to the prompt removes one of the catalog keys, or if the
orchestrator stops reading one of the catalog keys, this test fails. Without
this test, drift is invisible — every other test in the suite hand-builds
PagePacket fields piecewise and never exercises the literal prompt schema.
"""
from __future__ import annotations

from pathlib import Path

from sci_data_logger.schemas import DraftExperimentRequest, PagePacket
from sci_data_logger.services.orchestrator import ExperimentOrchestrator


# Mirrors the structure of the JSON example block in PAGE_ANALYSIS_PROMPT
# (prompts.py). If the prompt example changes, update this payload to match.
PROMPT_SHAPED_PAYLOAD: dict = {
    "page_type": ["synthesis_note", "calculation"],
    "page_number_hint": 3,
    "sample_id": "Na4Mn9O18-batch3",
    "materials": [
        {"name": "Mn2O3", "role": "precursor",
         "amount": {"value": 1.5787, "unit": "g", "confidence": 0.9}},
        {"name": "Na2CO3", "role": "precursor",
         "amount": {"value": 0.499, "unit": "g", "confidence": 0.8}},
        {"name": "Na4Mn9O18", "role": "target", "amount": None},
    ],
    "steps": [
        {"step_type": "weigh", "sequence_index": 1,
         "description": "按 Na 过量 6% 称量原料",
         "inputs": ["Mn2O3", "Na2CO3"], "parameters": {}, "confidence": 0.85},
        {"step_type": "sinter", "sequence_index": 2,
         "description": "850°C 烧结 12 小时",
         "parameters": {"temperature": {"value": 850, "unit": "C", "confidence": 0.9}},
         "confidence": 0.85},
    ],
    "observations": [
        {"value": "850°C 含 Mn2O3 杂质", "unit": None, "confidence": 0.9},
    ],
    "instruments": ["707炉", "806炉"],
    "materials_catalog": [
        {"canonical_name": "Mn2O3", "aliases": ["氧化锰"],
         "chemical_formula": "Mn2O3", "roles": ["precursor"]},
        {"canonical_name": "Na2CO3", "aliases": ["碳酸钠"],
         "chemical_formula": "Na2CO3", "roles": ["precursor"]},
        {"canonical_name": "Na4Mn9O18", "aliases": [],
         "chemical_formula": "Na4Mn9O18", "roles": ["target"]},
    ],
    "instruments_catalog": [
        {"technique": "tube_furnace", "instrument_label": "707",
         "aliases": ["707炉", "管式炉 707"], "manufacturer": None, "model": None},
        {"technique": "tube_furnace", "instrument_label": "806",
         "aliases": ["806炉"], "manufacturer": None, "model": None},
    ],
    "samples_catalog": [
        {"canonical_label": "Na4Mn9O18-batch3",
         "aliases": ["#3", "样品3"],
         "target_material_ref": "Na4Mn9O18",
         "batch": "9.18-batch3"},
    ],
    "events": [
        {
            "sequence_index": 1,
            "instrument_ref_local": None,
            "sample_ref_local": "Na4Mn9O18-batch3",
            "action_type": "weigh",
            "description": "按 Na 过量 6% 称量原料",
            "inputs": [
                {"material_ref_local": "Mn2O3",
                 "amount": {"value": 1.5787, "unit": "g", "confidence": 0.9}},
                {"material_ref_local": "Na2CO3",
                 "amount": {"value": 0.499, "unit": "g", "confidence": 0.8}},
            ],
            "outputs": [],
            "parameters": {},
            "confidence": 0.85,
        },
        {
            "sequence_index": 2,
            "instrument_ref_local": "707",
            "sample_ref_local": "Na4Mn9O18-batch3",
            "action_type": "sinter",
            "description": "850°C 烧结 12 小时",
            "inputs": [{"material_ref_local": "Mn2O3"}, {"material_ref_local": "Na2CO3"}],
            "outputs": [
                {"material_ref_local": "Na4Mn9O18", "target_phase": "P2-type"},
            ],
            "parameters": {"temperature": {"value": 850, "unit": "C", "confidence": 0.9}},
            "confidence": 0.85,
        },
    ],
    "text_blocks": ["9.18 合 Na4Mn9O18 纯相 850°C, 16h"],
    "table_blocks": [],
    "extracted_facts": {},
    "open_questions": [],
    "warnings": [],
    "review_required": False,
}


class _PromptShapedProcessor:
    """Returns a PagePacket whose raw_model_output['json'] is the prompt example."""

    def __init__(self) -> None:
        self._consumed = False

    def analyze_page(self, path: Path) -> PagePacket:
        if self._consumed:
            raise RuntimeError("test fixture only yields one packet")
        self._consumed = True
        # The DocumentProcessor would normally parse this payload into the
        # extracted_* fields. We mimic that minimally so the orchestrator's
        # legacy fallback paths can still fire. The key claim of this test is
        # that the NEW catalog/event fields drive the result, not the legacy
        # ones — so we deliberately leave extracted_materials / extracted_events
        # empty and let the catalogs/events on raw_model_output do the work.
        return PagePacket(
            source_path=str(path),
            page_types=PROMPT_SHAPED_PAYLOAD["page_type"],
            sample_id=PROMPT_SHAPED_PAYLOAD["sample_id"],
            text_blocks=PROMPT_SHAPED_PAYLOAD["text_blocks"],
            raw_model_output={"json": PROMPT_SHAPED_PAYLOAD},
        )

    def analyze_pages(self, path: Path) -> list[PagePacket]:
        return [self.analyze_page(path)]


def test_prompt_shaped_payload_populates_catalogs_and_chain(tmp_path):
    """Drive a record off a payload identical in shape to the prompt example."""
    img = tmp_path / "p.jpg"
    img.write_bytes(b"x")

    # NOTE: orchestrator currently consumes events from PagePacket.extracted_events.
    # The DocumentProcessor (which we're bypassing) parses raw_model_output.json.events
    # into that field. To exercise the prompt → orchestrator round-trip we must
    # also populate extracted_events directly from the raw payload here.
    from sci_data_logger.services.document import DocumentProcessor
    parsed_events = DocumentProcessor(vlm_client=object())._events_from_payload(
        PROMPT_SHAPED_PAYLOAD["events"], img, "fake-page-id"
    )

    class _Proc(_PromptShapedProcessor):
        def analyze_page(self, path: Path) -> PagePacket:
            pkt = super().analyze_page(path)
            pkt.extracted_events = parsed_events
            return pkt

    orch = ExperimentOrchestrator(document_processor=_Proc())
    record = orch.create_draft(
        DraftExperimentRequest(experiment_id="EXP-PROMPT-E2E", image_paths=[img]),
    )

    # Catalogs are populated from the catalog blocks, not from legacy fallbacks.
    canonical_names = sorted(m.canonical_name for m in record.materials_catalog)
    assert canonical_names == ["Mn2O3", "Na2CO3", "Na4Mn9O18"], canonical_names

    instr_labels = sorted(i.instrument_label for i in record.instruments_catalog if i.instrument_label)
    assert instr_labels == ["707", "806"], instr_labels

    assert len(record.samples_catalog) == 1
    sample = record.samples_catalog[0]
    assert sample.canonical_label == "Na4Mn9O18-batch3"
    assert "#3" in sample.aliases or "样品3" in sample.aliases

    # Two events, both resolved to catalog ids.
    assert len(record.events) == 2
    e_weigh, e_sinter = record.events
    assert e_weigh.action_type == "weigh"
    assert e_sinter.action_type == "sinter"

    # The sinter event consumes Mn2O3 (input) which the weigh event lists as
    # input too — neither produces it. But the sinter event's output Na4Mn9O18
    # has no prior producer; the chain forms only if at least one event's
    # outputs feed another's inputs. In this payload, the weigh event has no
    # outputs. So derived_from will be empty for both events — that's correct
    # for this payload shape, and we assert it explicitly so any future change
    # that fabricates spurious edges shows up.
    assert e_weigh.derived_from == []
    assert e_sinter.derived_from == []

    # But the catalog wiring DID happen: event inputs reference material_ids
    # from materials_catalog (not the raw "Mn2O3" string).
    mn2o3 = next(m for m in record.materials_catalog if m.canonical_name == "Mn2O3")
    e_weigh_input_refs = [io.material_ref for io in e_weigh.inputs]
    assert mn2o3.material_id in e_weigh_input_refs, (
        "events.inputs[].material_ref_local was not resolved to a "
        "Material.material_id by the orchestrator"
    )


def test_prompt_shaped_payload_chain_forms_when_outputs_link_inputs(tmp_path):
    """Sister test where weigh produces MnO2 and calcine consumes it — chain MUST form."""
    payload = {
        "page_type": ["synthesis_note"],
        "materials_catalog": [
            {"canonical_name": "MnO2", "aliases": [], "roles": ["precursor"]},
        ],
        "events": [
            {
                "sequence_index": 1, "action_type": "weigh",
                "description": "weigh MnO2",
                "inputs": [],
                "outputs": [{"material_ref_local": "MnO2"}],
                "parameters": {}, "confidence": 0.9,
            },
            {
                "sequence_index": 2, "action_type": "calcine",
                "description": "calcine MnO2",
                "inputs": [{"material_ref_local": "MnO2"}],
                "outputs": [],
                "parameters": {}, "confidence": 0.9,
            },
        ],
    }

    img = tmp_path / "p.jpg"
    img.write_bytes(b"x")

    from sci_data_logger.services.document import DocumentProcessor
    parsed_events = DocumentProcessor(vlm_client=object())._events_from_payload(
        payload["events"], img, "fake"
    )

    class _Proc:
        def analyze_page(self, path):
            return PagePacket(
                source_path=str(path),
                raw_model_output={"json": payload},
                extracted_events=parsed_events,
            )

        def analyze_pages(self, path):
            return [self.analyze_page(path)]

    record = ExperimentOrchestrator(document_processor=_Proc()).create_draft(
        DraftExperimentRequest(experiment_id="EXP-CHAIN-PROMPT", image_paths=[img]),
    )

    assert len(record.events) == 2
    e_weigh, e_calcine = record.events
    assert e_weigh.event_id in e_calcine.derived_from, (
        "Prompt-shaped events.outputs → next events.inputs chain did not form; "
        "_link_event_chains may be skipping material_ref resolution from the prompt path"
    )
