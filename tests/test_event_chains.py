"""Tests for causal-chain linking between experiment events.

These tests exercise ``ExperimentOrchestrator._link_event_chains``: given a
list of events whose inputs/outputs reference shared materials, the linker
must populate ``derived_from`` and ``produces_for`` so that each event
records its strictly-earlier producers and later consumers. The acyclicity
guarantee (producer ``sequence_index`` < consumer ``sequence_index``) is
also covered here.
"""

from sci_data_logger.schemas import (
    DraftExperimentRequest,
    EventIO,
    EventOutput,
    ExperimentEvent,
    PagePacket,
)
from sci_data_logger.services.orchestrator import ExperimentOrchestrator


class _FakeDocumentProcessor:
    """Injects pre-constructed PagePacket list (mirrors test_orchestrator_event_merge)."""

    def __init__(self, pages):
        self._pages = list(pages)

    def analyze_page(self, path):
        return self._pages.pop(0)

    def analyze_pages(self, path):
        return [self.analyze_page(path)]


def test_link_event_chains_links_consumer_to_producer():
    a = ExperimentEvent(
        sequence_index=1,
        action_type="weigh",
        description="weigh MnO2",
        page_ref="page_1",
        outputs=[EventOutput(material_ref="mat_X")],
    )
    b = ExperimentEvent(
        sequence_index=2,
        action_type="calcine",
        description="calcine MnO2",
        page_ref="page_1",
        inputs=[EventIO(material_ref="mat_X")],
    )

    linked = ExperimentOrchestrator._link_event_chains([a, b])
    by_id = {e.event_id: e for e in linked}
    assert by_id[b.event_id].derived_from == [a.event_id]
    assert by_id[a.event_id].produces_for == [b.event_id]


def test_link_event_chains_ignores_self_and_future_producers():
    a = ExperimentEvent(
        sequence_index=2,
        action_type="weigh",
        description="A later step that outputs mat_X",
        page_ref="page_1",
        outputs=[EventOutput(material_ref="mat_X")],
    )
    b = ExperimentEvent(
        sequence_index=1,
        action_type="calcine",
        description="An earlier step that consumes mat_X",
        page_ref="page_1",
        inputs=[EventIO(material_ref="mat_X")],
    )

    linked = ExperimentOrchestrator._link_event_chains([a, b])
    by_id = {e.event_id: e for e in linked}
    # B is BEFORE A, so B cannot depend on A
    assert by_id[b.event_id].derived_from == []
    assert by_id[a.event_id].produces_for == []


def test_link_event_chains_handles_chain_of_three():
    a = ExperimentEvent(
        sequence_index=1,
        action_type="weigh",
        description="produce M1",
        page_ref="page_1",
        outputs=[EventOutput(material_ref="M1")],
    )
    b = ExperimentEvent(
        sequence_index=2,
        action_type="mix",
        description="consume M1, produce M2",
        page_ref="page_1",
        inputs=[EventIO(material_ref="M1")],
        outputs=[EventOutput(material_ref="M2")],
    )
    c = ExperimentEvent(
        sequence_index=3,
        action_type="calcine",
        description="consume M2",
        page_ref="page_1",
        inputs=[EventIO(material_ref="M2")],
    )

    linked = ExperimentOrchestrator._link_event_chains([a, b, c])
    by_id = {e.event_id: e for e in linked}
    assert by_id[b.event_id].derived_from == [a.event_id]
    assert by_id[c.event_id].derived_from == [b.event_id]
    assert by_id[a.event_id].produces_for == [b.event_id]
    assert by_id[b.event_id].produces_for == [c.event_id]
    # endpoints have empty reverse edges
    assert by_id[a.event_id].derived_from == []
    assert by_id[c.event_id].produces_for == []


def test_end_to_end_event_chains_via_orchestrator(tmp_path):
    page1 = PagePacket(source_path="p1.jpg")
    page1.raw_model_output = {
        "json": {
            "materials_catalog": [
                {"canonical_name": "MnO2", "role": "precursor"},
            ],
        }
    }
    page1.extracted_events = [
        ExperimentEvent(
            sequence_index=1,
            action_type="weigh",
            description="weigh MnO2",
            page_ref=page1.page_id,
            outputs=[EventOutput(material_ref="MnO2")],
        )
    ]

    page2 = PagePacket(source_path="p2.jpg")
    page2.raw_model_output = {"json": {"materials_catalog": []}}
    page2.extracted_events = [
        ExperimentEvent(
            sequence_index=1,
            action_type="calcine",
            description="calcine MnO2",
            page_ref=page2.page_id,
            inputs=[EventIO(material_ref="MnO2")],
        )
    ]

    img1 = tmp_path / "p1.jpg"
    img1.write_bytes(b"x")
    img2 = tmp_path / "p2.jpg"
    img2.write_bytes(b"x")

    orch = ExperimentOrchestrator(
        document_processor=_FakeDocumentProcessor([page1, page2]),
    )
    record = orch.create_draft(
        DraftExperimentRequest(
            experiment_id="EXP-CHAIN", image_paths=[img1, img2]
        )
    )

    assert len(record.events) == 2
    e0, e1 = record.events[0], record.events[1]
    assert e0.action_type == "weigh"
    assert e1.action_type == "calcine"
    assert e0.event_id in e1.derived_from
    assert e1.event_id in e0.produces_for


def test_legacy_steps_upgrade_preserves_io_for_chain_linking(tmp_path):
    """When VLM emits legacy `steps` instead of `events`, the orchestrator
    upgrades them to ExperimentEvent. That upgrade must copy inputs/outputs so
    _link_event_chains can find producer→consumer edges; otherwise Gap 6 fix
    is dead under the legacy prompt path.
    """
    from sci_data_logger.schemas import ProtocolStep

    page = PagePacket(source_path="legacy.jpg")
    # Catalog provided so the references resolve.
    page.raw_model_output = {
        "json": {
            "materials_catalog": [
                {"canonical_name": "MnO2", "role": "precursor"},
            ],
        }
    }
    # Legacy steps with inputs/outputs but no `events`.
    page.extracted_steps = [
        ProtocolStep(
            step_type="weigh",
            sequence_index=1,
            description="weigh MnO2",
            inputs=[],
            outputs=["MnO2"],
        ),
        ProtocolStep(
            step_type="calcine",
            sequence_index=2,
            description="calcine MnO2",
            inputs=["MnO2"],
            outputs=[],
        ),
    ]

    img = tmp_path / "legacy.jpg"
    img.write_bytes(b"x")
    orch = ExperimentOrchestrator(
        document_processor=_FakeDocumentProcessor([page]),
    )
    record = orch.create_draft(
        DraftExperimentRequest(experiment_id="EXP-LEGACY", image_paths=[img]),
    )

    assert len(record.events) == 2
    e_weigh, e_calcine = record.events
    assert e_weigh.action_type == "weigh"
    assert e_calcine.action_type == "calcine"
    # IO must have been copied from ProtocolStep.
    assert [io.material_ref for io in e_weigh.outputs] != []
    assert [io.material_ref for io in e_calcine.inputs] != []
    # And the chain link must form.
    assert e_weigh.event_id in e_calcine.derived_from, (
        "step→event upgrade dropped material flow; _link_event_chains "
        "produces nothing under legacy prompt"
    )


def test_legacy_steps_upgrade_links_across_pages(tmp_path):
    """Cross-page version of the legacy upgrade test: page 1 produces MnO2 via
    legacy `steps`, page 2 consumes MnO2 via legacy `steps`. After global
    resequence in _resolve_and_merge_events the chain must form across pages,
    not just within a page. This pins the orchestrator's resequence-then-link
    ordering — if a future refactor moves _link_event_chains before global
    resequence, this test catches the silent regression.
    """
    from sci_data_logger.schemas import ProtocolStep

    page1 = PagePacket(source_path="p1.jpg")
    page1.raw_model_output = {
        "json": {"materials_catalog": [{"canonical_name": "MnO2", "role": "precursor"}]}
    }
    page1.extracted_steps = [
        ProtocolStep(
            step_type="weigh",
            sequence_index=1,
            description="weigh MnO2 on page 1",
            inputs=[],
            outputs=["MnO2"],
        ),
    ]

    page2 = PagePacket(source_path="p2.jpg")
    page2.raw_model_output = {"json": {"materials_catalog": []}}
    page2.extracted_steps = [
        ProtocolStep(
            step_type="calcine",
            sequence_index=1,  # NOTE: collides with page1's seq_index until global resequence
            description="calcine MnO2 on page 2",
            inputs=["MnO2"],
            outputs=[],
        ),
    ]

    img1 = tmp_path / "p1.jpg"
    img1.write_bytes(b"x")
    img2 = tmp_path / "p2.jpg"
    img2.write_bytes(b"x")
    orch = ExperimentOrchestrator(
        document_processor=_FakeDocumentProcessor([page1, page2]),
    )
    record = orch.create_draft(
        DraftExperimentRequest(experiment_id="EXP-LEGACY-XPAGE", image_paths=[img1, img2]),
    )

    assert len(record.events) == 2
    e_weigh, e_calcine = record.events  # global sort: page0 then page1
    assert e_weigh.action_type == "weigh"
    assert e_calcine.action_type == "calcine"
    assert e_weigh.event_id in e_calcine.derived_from, (
        "cross-page legacy chain broken: producer on page 1, consumer on page 2 "
        "did not link via _link_event_chains. Did somebody move the call "
        "before global resequence?"
    )
    assert e_calcine.event_id in e_weigh.produces_for
