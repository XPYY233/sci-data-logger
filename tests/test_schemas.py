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


def test_material_defaults_and_required_fields():
    from sci_data_logger.schemas import Material

    m = Material(canonical_name="Mn2O3")
    assert m.canonical_name == "Mn2O3"
    assert m.display_name is None
    assert m.aliases == []
    assert m.chemical_formula is None
    assert m.role is None
    assert m.metadata == {}
    assert m.material_id.startswith("mat_")

    m2 = Material(canonical_name="LiCl", display_name="氯化锂",
                  aliases=["LiCl·H2O"], chemical_formula="LiCl",
                  role="precursor")
    assert m2.role == "precursor"
    assert "LiCl·H2O" in m2.aliases
