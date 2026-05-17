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
    assert m.roles == []
    assert m.metadata == {}
    assert m.material_id.startswith("mat_")

    m2 = Material(canonical_name="LiCl", display_name="氯化锂",
                  aliases=["LiCl·H2O"], chemical_formula="LiCl",
                  roles=["precursor"])
    assert m2.roles == ["precursor"]
    assert "LiCl·H2O" in m2.aliases


def test_instrument_defaults_and_label_split():
    """关键场景：'707球磨' 必须能拆成 technique=ball_mill + instrument_label='707'."""
    from sci_data_logger.schemas import Instrument

    ins = Instrument(technique="ball_mill", instrument_label="707",
                     model="高能行星球磨")
    assert ins.technique == "ball_mill"
    assert ins.instrument_label == "707"
    assert ins.location is None
    assert ins.model == "高能行星球磨"
    assert ins.instrument_id.startswith("instr_")

    import pytest
    with pytest.raises(Exception):
        Instrument()


def test_event_io_models():
    from sci_data_logger.schemas import EventIO, EventOutput, FieldValue

    io = EventIO(material_ref="mat_abc", amount=FieldValue(value=1.5, unit="g"))
    assert io.material_ref == "mat_abc"
    assert io.amount.value == 1.5
    assert io.notes is None

    out = EventOutput(material_ref="mat_xyz",
                     amount=FieldValue(value=2.5, unit="g"),
                     target_phase="P-3m1",
                     failure_marker="没合成")
    assert out.target_phase == "P-3m1"
    assert out.failure_marker == "没合成"
    assert out.material_ref == "mat_xyz"


def test_experiment_event_defaults_and_required():
    from sci_data_logger.schemas import (
        ExperimentEvent, EventIO, EventOutput, FieldValue
    )

    e = ExperimentEvent(
        sequence_index=1,
        action_type="mill",
        description="600rpm 15h 高能行星球磨",
        page_ref="page_xxx",
    )
    assert e.event_id.startswith("evt_")
    assert e.sequence_index == 1
    assert e.date_label is None
    assert e.date_iso is None
    assert e.location is None
    assert e.instrument_ref is None
    assert e.operator is None
    assert e.inputs == []
    assert e.outputs == []
    assert e.parameters == {}
    assert e.recipe_ratio is None
    assert e.equation is None
    assert e.observations == []
    assert e.evidence_refs == []
    assert e.confidence is None

    full = ExperimentEvent(
        sequence_index=2,
        date_label="5.20",
        action_type="mill",
        description="...",
        page_ref="page_yyy",
        inputs=[EventIO(material_ref="mat_a")],
        outputs=[EventOutput(material_ref="mat_b", failure_marker="X")],
        parameters={"speed": FieldValue(value=600, unit="rpm")},
        equation="A + B = C",
        recipe_ratio={"target_element": "Na", "excess_pct": 7},
        confidence=0.9,
    )
    assert full.equation == "A + B = C"
    assert full.recipe_ratio["excess_pct"] == 7
    assert full.outputs[0].failure_marker == "X"


def test_experiment_event_derived_from_and_produces_for_default_empty():
    from sci_data_logger.schemas import ExperimentEvent

    e = ExperimentEvent(
        sequence_index=1,
        action_type="mill",
        description="球磨",
        page_ref="page_xxx",
    )
    assert e.derived_from == []
    assert e.produces_for == []


def test_page_packet_new_extracted_fields_default_empty():
    from sci_data_logger.schemas import PagePacket

    p = PagePacket(source_path="x.jpg")
    # 已有字段
    assert p.page_types == ["unknown"]
    assert p.sample_id is None
    # 新增字段默认值
    assert p.extracted_dates == []
    assert p.extracted_locations == []
    assert p.extracted_batches == []
    assert p.extracted_equations == []
    assert p.extracted_target_phases == []
    assert p.extracted_failure_markers == []
    assert p.extracted_recipe_ratios == []
    assert p.extracted_events == []


def test_experiment_record_catalogs_and_compat_properties():
    from sci_data_logger.schemas import (
        ExperimentRecord, Material, ExperimentEvent,
        EventIO, EventOutput, FieldValue,
    )

    # 空 catalogs：兼容 property 退化为空
    rec = ExperimentRecord(experiment_id="EXP-0")
    assert rec.materials_catalog == []
    assert rec.instruments_catalog == []
    assert rec.events == []
    assert rec.materials == []   # property 派生
    assert rec.steps == []
    assert rec.observations == []

    # 填充 catalog + events
    mat_a = Material(canonical_name="LiCl", roles=["precursor"])
    mat_b = Material(canonical_name="Li2ZrCl6", roles=["target"])
    evt = ExperimentEvent(
        sequence_index=1,
        action_type="mill",
        description="球磨",
        page_ref="page_xxx",
        inputs=[EventIO(material_ref=mat_a.material_id)],
        outputs=[EventOutput(material_ref=mat_b.material_id, failure_marker="X")],
        observations=[FieldValue(value="没合成", confidence=0.9)],
    )
    rec2 = ExperimentRecord(
        experiment_id="EXP-1",
        materials_catalog=[mat_a, mat_b],
        events=[evt],
    )
    assert len(rec2.materials) == 2
    assert {m.name for m in rec2.materials} == {"LiCl", "Li2ZrCl6"}
    assert len(rec2.steps) == 1
    assert rec2.steps[0].step_type == "mill"
    assert rec2.steps[0].description == "球磨"
    assert rec2.steps[0].sequence_index == 1
    assert len(rec2.observations) == 1
    assert rec2.observations[0].value == "没合成"


def test_sample_defaults_and_required_fields():
    from sci_data_logger.schemas import Sample

    s = Sample(canonical_label="S3")
    assert s.canonical_label == "S3"
    assert s.display_label is None
    assert s.aliases == []
    assert s.target_material_ref is None
    assert s.batch is None
    assert s.metadata == {}
    assert s.sample_id.startswith("sample_")

    s2 = Sample(canonical_label="样品3", display_label="样品 3",
                aliases=["#3", "S3"], target_material_ref="mat_abc",
                batch="2024-Q1")
    assert s2.batch == "2024-Q1"
    assert "#3" in s2.aliases
    assert s2.target_material_ref == "mat_abc"


def test_experiment_event_sample_ref_default_none():
    from sci_data_logger.schemas import ExperimentEvent

    e = ExperimentEvent(
        sequence_index=1,
        action_type="mill",
        description="球磨",
        page_ref="page_xxx",
    )
    assert e.sample_ref is None

    e2 = ExperimentEvent(
        sequence_index=2,
        action_type="mill",
        description="球磨",
        page_ref="page_yyy",
        sample_ref="sample_abc",
    )
    assert e2.sample_ref == "sample_abc"


def test_experiment_record_samples_catalog_default_empty():
    from sci_data_logger.schemas import ExperimentRecord, Sample

    rec = ExperimentRecord(experiment_id="EXP-S")
    assert rec.samples_catalog == []

    rec2 = ExperimentRecord(
        experiment_id="EXP-S2",
        samples_catalog=[Sample(canonical_label="S3")],
    )
    assert len(rec2.samples_catalog) == 1
    assert rec2.samples_catalog[0].canonical_label == "S3"
