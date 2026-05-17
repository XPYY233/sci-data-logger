from __future__ import annotations

from pathlib import Path

from extensions.personalization.config import build_profiles_from_answers, load_effective_profile
from extensions.personalization.service import analyze_wet_record


def _answers() -> dict:
    return {
        "user_id": "fanjunran",
        "display_name": "范君然",
        "user_term_aliases": {"一烧": "calcine_stage_1"},
        "sample_id_patterns": ["HEA-{date}-{seq}"],
        "user_preferred_fields": ["heating_rate"],
        "user_required_fields": ["atmosphere"],
        "handwriting_notes": ["1 与 7 易混淆"],
        "experiment_template_id": "solid_state_synthesis",
        "experiment_display_name": "固相合成",
        "experiment_required_fields": ["temperature"],
        "experiment_preferred_fields": ["duration"],
        "common_step_types": ["calcine"],
        "experiment_term_aliases": {"预烧": "calcine"},
        "instrument_id": "lab_xrd",
        "instrument_display_name": "实验室 XRD",
        "technique": "XRD",
        "file_patterns": ["*lab-xrd*"],
        "field_mappings": {"KV": "tube_voltage_kv"},
        "focus_parameters": ["tube_voltage_kv"],
    }


def test_profiles_merge_shared_templates_and_local_overrides(tmp_path: Path) -> None:
    build_profiles_from_answers(_answers(), tmp_path)

    profile = load_effective_profile(
        user_id="fanjunran",
        experiment_template_id="solid_state_synthesis",
        instrument_id="lab_xrd",
        local_root=tmp_path,
    )

    assert "experiment_id" in profile["required_fields"]
    assert "temperature" in profile["required_fields"]
    assert "atmosphere" in profile["required_fields"]
    assert profile["term_aliases"]["预烧"] == "calcine"
    assert profile["term_aliases"]["一烧"] == "calcine_stage_1"
    assert profile["field_mappings"]["KV"] == "tube_voltage_kv"


def test_personalized_analysis_changes_step_semantics_and_review_rules() -> None:
    profile = {
        "required_fields": ["sample_id", "temperature"],
        "term_aliases": {"预烧": "calcine"},
        "profile_context": {"user_id": "fanjunran"},
    }
    record = {
        "experiment_id": "EXP-001",
        "pages": [
            {
                "sample_id": "S-1",
                "extracted_steps": [{"step_type": "预烧", "description": "500°C 预烧"}],
                "extracted_facts": {},
            }
        ],
    }

    result = analyze_wet_record(record, profile)

    assert result["normalized_steps"][0]["normalized_step_type"] == "calcine"
    assert result["missing_required_fields"] == ["temperature"]
    assert result["review_issues"][0]["field"] == "temperature"
