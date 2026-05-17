"""Phase 1 completion verification tests.

Validates each acceptance criterion from the incremental extension roadmap:
1. Wizard can generate user / experiment / instrument profiles
2. Local overrides correctly override shared templates (merge chain)
3. Same wet-lab input produces observably different output in default vs personalized mode
4. Missing personalized required fields generate expected review issues
5. Without loading extensions, the main project behavior stays unchanged
"""
from __future__ import annotations

import json
from pathlib import Path

from extensions.personalization.cli import main as personalization_cli
from extensions.personalization.config import (
    build_profiles_from_answers,
    load_effective_profile,
    local_profile_path,
)
from extensions.personalization.repository import (
    connect as personalization_db_connect,
)
from extensions.personalization.service import analyze_and_store, analyze_wet_record


def _sample_answers() -> dict:
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


def _sample_wet_record() -> dict:
    """A minimal but realistic wet-lab experiment record."""
    return {
        "experiment_id": "EXP-001",
        "operator": "范君然",
        "project_id": "PRJ-HEA",
        "pages": [
            {
                "sample_id": "HEA-20260517-01",
                "extracted_materials": [{"name": "MoO3", "amount": "5g"}],
                "extracted_steps": [
                    {"step_type": "预烧", "description": "500°C 预烧 4h"},
                    {"step_type": "一烧", "description": "900°C 一烧 12h"},
                ],
                "extracted_facts": {"temperature": "500"},
            }
        ],
        "events": [
            {
                "action_type": "预烧",
                "description": "500°C 预烧 4h",
                "sequence_index": 0,
            },
        ],
    }


# ─── Criterion 1: Wizard generates profiles ─────────────────────────────


class TestWizardGeneratesProfiles:
    def test_wizard_creates_all_three_profile_files(self, tmp_path: Path) -> None:
        paths = build_profiles_from_answers(_sample_answers(), tmp_path)
        assert "user" in paths
        assert "experiment" in paths
        assert "instrument" in paths
        for p in paths.values():
            assert p.exists()

    def test_wizard_user_profile_content(self, tmp_path: Path) -> None:
        build_profiles_from_answers(_sample_answers(), tmp_path)
        user_path = local_profile_path("users", "fanjunran", tmp_path)
        data = json.loads(user_path.read_text())
        assert data["user_id"] == "fanjunran"
        assert data["display_name"] == "范君然"
        assert data["term_aliases"]["一烧"] == "calcine_stage_1"
        assert "HEA-{date}-{seq}" in data["sample_id_patterns"]
        assert "atmosphere" in data["required_fields"]

    def test_wizard_experiment_template_content(self, tmp_path: Path) -> None:
        build_profiles_from_answers(_sample_answers(), tmp_path)
        exp_path = local_profile_path("experiments", "solid_state_synthesis", tmp_path)
        data = json.loads(exp_path.read_text())
        assert data["template_id"] == "solid_state_synthesis"
        assert "temperature" in data["required_fields"]
        assert data["term_aliases"]["预烧"] == "calcine"

    def test_wizard_instrument_template_content(self, tmp_path: Path) -> None:
        build_profiles_from_answers(_sample_answers(), tmp_path)
        inst_path = local_profile_path("instruments", "lab_xrd", tmp_path)
        data = json.loads(inst_path.read_text())
        assert data["instrument_id"] == "lab_xrd"
        assert data["technique"] == "XRD"
        assert data["field_mappings"]["KV"] == "tube_voltage_kv"

    def test_wizard_persists_to_sidecar_db(self, tmp_path: Path) -> None:
        db_path = tmp_path / "personalization.db"
        from extensions.personalization.service import create_profiles_from_answers

        create_profiles_from_answers(_sample_answers(), local_root=tmp_path, db_path=db_path)
        conn = personalization_db_connect(db_path)
        rows = conn.execute("SELECT * FROM profiles ORDER BY profile_type, profile_id").fetchall()
        conn.close()
        assert len(rows) == 3
        types = {row["profile_type"] for row in rows}
        assert types == {"users", "experiments", "instruments"}

    def test_cli_wizard_with_answers_json(self, tmp_path: Path) -> None:
        answers_path = tmp_path / "answers.json"
        answers_path.write_text(json.dumps(_sample_answers(), ensure_ascii=False))
        db_path = tmp_path / "personalization.db"
        ret = personalization_cli([
            "wizard",
            "--answers-json", str(answers_path),
            "--local-root", str(tmp_path),
            "--db-path", str(db_path),
        ])
        assert ret == 0
        assert local_profile_path("users", "fanjunran", tmp_path).exists()


# ─── Criterion 2: Local overrides correctly override shared templates ────


class TestMergeChain:
    def test_default_only_profile(self, tmp_path: Path) -> None:
        """Without any user/experiment/instrument override, defaults + group apply."""
        profile = load_effective_profile(local_root=tmp_path)
        assert "experiment_id" in profile["required_fields"]
        # group template adds: operator, sample_id, materials, protocol_steps
        assert "operator" in profile["required_fields"]
        assert "sample_id" in profile["required_fields"]

    def test_group_template_overrides_default(self) -> None:
        """Group template adds term_aliases not present in defaults."""
        profile = load_effective_profile(group_id="materials_default")
        assert profile["term_aliases"]["煅烧"] == "calcine"

    def test_experiment_template_overrides_group(self, tmp_path: Path) -> None:
        """Experiment template adds experiment-specific required_fields and aliases."""
        profile = load_effective_profile(
            experiment_template_id="solid_state_synthesis", local_root=tmp_path
        )
        assert "temperature" in profile["required_fields"]
        assert "duration" in profile["required_fields"]
        # Experiment alias overrides group
        assert profile["term_aliases"]["预烧"] == "calcine"

    def test_user_override_overrides_everything(self, tmp_path: Path) -> None:
        """User-level required_fields should merge on top of everything."""
        build_profiles_from_answers(_sample_answers(), tmp_path)
        profile = load_effective_profile(
            user_id="fanjunran",
            experiment_template_id="solid_state_synthesis",
            instrument_id="lab_xrd",
            local_root=tmp_path,
        )
        # user adds "atmosphere" as required
        assert "atmosphere" in profile["required_fields"]
        # user alias "一烧" is present
        assert profile["term_aliases"]["一烧"] == "calcine_stage_1"
        # earlier layers still present
        assert "experiment_id" in profile["required_fields"]
        assert profile["term_aliases"]["预烧"] == "calcine"

    def test_merge_priority_local_over_shared(self, tmp_path: Path) -> None:
        """If local override has a conflicting alias, local wins."""
        answers = _sample_answers()
        answers["user_term_aliases"] = {"预烧": "user_pre_calcine"}
        build_profiles_from_answers(answers, tmp_path)
        profile = load_effective_profile(
            user_id="fanjunran",
            experiment_template_id="solid_state_synthesis",
            local_root=tmp_path,
        )
        # user layer overrides experiment layer alias
        assert profile["term_aliases"]["预烧"] == "user_pre_calcine"

    def test_instrument_field_mappings_merge(self, tmp_path: Path) -> None:
        build_profiles_from_answers(_sample_answers(), tmp_path)
        profile = load_effective_profile(
            instrument_id="lab_xrd",
            local_root=tmp_path,
        )
        assert profile["field_mappings"]["KV"] == "tube_voltage_kv"

    def test_profile_context_recorded(self, tmp_path: Path) -> None:
        build_profiles_from_answers(_sample_answers(), tmp_path)
        profile = load_effective_profile(
            user_id="fanjunran",
            experiment_template_id="solid_state_synthesis",
            instrument_id="lab_xrd",
            local_root=tmp_path,
        )
        ctx = profile.get("profile_context", {})
        assert ctx["user_id"] == "fanjunran"
        assert ctx["experiment_template_id"] == "solid_state_synthesis"
        assert ctx["instrument_id"] == "lab_xrd"


# ─── Criterion 3: Same input → observably different output ──────────────


class TestPersonalizedVsDefault:
    def test_default_analysis_no_term_normalization(self) -> None:
        """Without personalization, step_type '预烧' stays as-is."""
        default_profile = load_effective_profile()
        record = _sample_wet_record()
        result = analyze_wet_record(record, default_profile)
        # default profile has no alias for '预烧' in group template? Actually group has 煅烧→calcine
        # but not 预烧, so 预烧 should NOT be normalized
        pre_steps = [s for s in result["normalized_steps"] if s["raw_step_type"] == "预烧"]
        assert len(pre_steps) >= 1
        # group template only has 煅烧→calcine, not 预烧→calcine
        assert pre_steps[0]["normalized_step_type"] == "预烧"

    def test_personalized_analysis_normalizes_aliases(self, tmp_path: Path) -> None:
        """With personalization (experiment template), '预烧' normalizes to 'calcine'."""
        build_profiles_from_answers(_sample_answers(), tmp_path)
        profile = load_effective_profile(
            user_id="fanjunran",
            experiment_template_id="solid_state_synthesis",
            local_root=tmp_path,
        )
        record = _sample_wet_record()
        result = analyze_wet_record(record, profile)
        pre_steps = [s for s in result["normalized_steps"] if s["raw_step_type"] == "预烧"]
        assert len(pre_steps) >= 1
        assert pre_steps[0]["normalized_step_type"] == "calcine"

    def test_user_alias_normalization(self, tmp_path: Path) -> None:
        """User-specific alias '一烧' should normalize to 'calcine_stage_1'."""
        build_profiles_from_answers(_sample_answers(), tmp_path)
        profile = load_effective_profile(
            user_id="fanjunran",
            local_root=tmp_path,
        )
        record = _sample_wet_record()
        result = analyze_wet_record(record, profile)
        yi_steps = [s for s in result["normalized_steps"] if s["raw_step_type"] == "一烧"]
        assert len(yi_steps) >= 1
        assert yi_steps[0]["normalized_step_type"] == "calcine_stage_1"

    def test_different_profiles_produce_different_missing_fields(self, tmp_path: Path) -> None:
        """Default vs personalized profiles should flag different missing required fields."""
        record = _sample_wet_record()
        record["pages"][0].pop("extracted_facts", None)

        # Default profile only requires experiment_id, operator, sample_id, materials, protocol_steps
        default_profile = load_effective_profile()
        default_result = analyze_wet_record(record, default_profile)
        default_missing = set(default_result["missing_required_fields"])

        # Personalized profile adds temperature, atmosphere, etc.
        build_profiles_from_answers(_sample_answers(), tmp_path)
        pers_profile = load_effective_profile(
            user_id="fanjunran",
            experiment_template_id="solid_state_synthesis",
            local_root=tmp_path,
        )
        pers_result = analyze_wet_record(record, pers_profile)
        pers_missing = set(pers_result["missing_required_fields"])

        # Personalized should have STRICTER requirements
        assert pers_missing >= default_missing
        assert "temperature" in pers_missing
        assert "atmosphere" in pers_missing


# ─── Criterion 4: Missing required fields → expected review issues ──────


class TestReviewIssues:
    def test_missing_personalized_field_generates_review_issue(self, tmp_path: Path) -> None:
        """When a user-required field is missing, a review issue should be created."""
        build_profiles_from_answers(_sample_answers(), tmp_path)
        profile = load_effective_profile(
            user_id="fanjunran",
            experiment_template_id="solid_state_synthesis",
            local_root=tmp_path,
        )
        # Record without atmosphere or temperature
        record = {"experiment_id": "EXP-002", "pages": []}
        result = analyze_wet_record(record, profile)
        issue_fields = {issue["field"] for issue in result["review_issues"]}
        assert "atmosphere" in issue_fields
        assert "temperature" in issue_fields

    def test_review_issue_structure(self, tmp_path: Path) -> None:
        build_profiles_from_answers(_sample_answers(), tmp_path)
        profile = load_effective_profile(user_id="fanjunran", local_root=tmp_path)
        record = {"experiment_id": "EXP-002", "pages": []}
        result = analyze_wet_record(record, profile)
        for issue in result["review_issues"]:
            assert issue["severity"] == "warning"
            assert "title" in issue
            assert "detail" in issue
            assert "field" in issue

    def test_no_issues_when_all_required_present(self, tmp_path: Path) -> None:
        """A complete record should produce no review issues for missing fields."""
        build_profiles_from_answers(_sample_answers(), tmp_path)
        profile = load_effective_profile(user_id="fanjunran", local_root=tmp_path)
        # Provide everything required
        record = {
            "experiment_id": "EXP-003",
            "operator": "范君然",
            "pages": [
                {
                    "sample_id": "S-1",
                    "extracted_materials": [{"name": "MoO3"}],
                    "extracted_steps": [{"step_type": "calcine", "description": "500°C"}],
                    "extracted_facts": {"atmosphere": "air"},
                }
            ],
        }
        result = analyze_wet_record(record, profile)
        assert result["missing_required_fields"] == []
        assert result["review_issues"] == []


# ─── Criterion 5: Main project unchanged without extensions ─────────────


class TestMainProjectIsolation:
    def test_schemas_import_without_extensions(self) -> None:
        """Core schemas should import cleanly with no extension dependency."""
        from sci_data_logger.schemas import ExperimentRecord

        record = ExperimentRecord(experiment_id="ISO-001")
        assert record.experiment_id == "ISO-001"
        assert record.status.value == "draft"

    def test_cli_import_without_extensions(self) -> None:
        """Core CLI should import cleanly."""
        from sci_data_logger.cli import app

        assert app is not None

    def test_draft_request_works_without_extensions(self) -> None:
        """Core DraftExperimentRequest should work without extension data."""
        from sci_data_logger.schemas import DraftExperimentRequest

        req = DraftExperimentRequest(experiment_id="ISO-002")
        assert req.experiment_id == "ISO-002"

    def test_analysis_run_stored_to_sidecar_db(self, tmp_path: Path) -> None:
        """analyze_and_store writes to the personalization sidecar DB, not the main DB."""
        db_path = tmp_path / "personalization.db"
        build_profiles_from_answers(_sample_answers(), tmp_path)
        record = _sample_wet_record()
        result = analyze_and_store(
            record,
            user_id="fanjunran",
            experiment_template_id="solid_state_synthesis",
            local_root=tmp_path,
            db_path=db_path,
        )
        assert "analysis_run_id" in result
        # Verify sidecar DB has the run
        conn = personalization_db_connect(db_path)
        rows = conn.execute("SELECT * FROM analysis_runs").fetchall()
        conn.close()
        assert len(rows) == 1
        assert rows[0]["run_id"] == result["analysis_run_id"]

    def test_cli_show_effective(self, tmp_path: Path) -> None:
        build_profiles_from_answers(_sample_answers(), tmp_path)
        ret = personalization_cli([
            "show-effective",
            "--user-id", "fanjunran",
            "--experiment-template", "solid_state_synthesis",
            "--instrument-template", "lab_xrd",
            "--local-root", str(tmp_path),
        ])
        assert ret == 0

    def test_cli_parse_with_output(self, tmp_path: Path) -> None:
        db_path = tmp_path / "personalization.db"
        build_profiles_from_answers(_sample_answers(), tmp_path)
        input_path = tmp_path / "record.json"
        input_path.write_text(json.dumps(_sample_wet_record(), ensure_ascii=False))
        output_path = tmp_path / "result.json"
        ret = personalization_cli([
            "parse",
            "--input", str(input_path),
            "--user-id", "fanjunran",
            "--experiment-template", "solid_state_synthesis",
            "--local-root", str(tmp_path),
            "--db-path", str(db_path),
            "--output", str(output_path),
        ])
        assert ret == 0
        assert output_path.exists()
        result = json.loads(output_path.read_text())
        assert "normalized_steps" in result
        assert "missing_required_fields" in result
