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
    # consumer has no producer downstream, producer has no consumer upstream
    assert by_id[a.event_id].derived_from == []
    assert by_id[b.event_id].produces_for == []


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
