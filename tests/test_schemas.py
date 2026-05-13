from sci_data_logger.schemas import DraftExperimentRequest, ExperimentRecord, PagePacket


def test_experiment_record_minimal() -> None:
    request = DraftExperimentRequest(experiment_id="EXP-001")
    record = ExperimentRecord(experiment_id=request.experiment_id)
    assert record.experiment_id == "EXP-001"
    assert record.status == "draft"


def test_page_packet_defaults() -> None:
    page = PagePacket(source_path="/tmp/test.jpg")
    assert page.page_types == ["unknown"]
    assert page.page_type == "unknown"
    assert page.sample_id is None
    assert page.extracted_materials == []
    assert page.extracted_steps == []
    assert page.extracted_observations == []
    assert page.extracted_instruments == []
    assert page.extracted_facts == {}
    assert page.review_required is False


def test_page_packet_page_type_property_reads_first() -> None:
    page = PagePacket(source_path="/tmp/x.jpg", page_types=["synthesis_note", "calculation"])
    assert page.page_type == "synthesis_note"


def test_page_packet_page_type_property_on_empty_list() -> None:
    page = PagePacket(source_path="/tmp/x.jpg", page_types=[])
    assert page.page_type == "unknown"
