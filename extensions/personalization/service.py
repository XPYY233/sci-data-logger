from __future__ import annotations

from pathlib import Path
from typing import Any

from .config import DEFAULT_LOCAL_ROOT, build_profiles_from_answers, load_effective_profile
from .repository import DEFAULT_DB_PATH, save_analysis_run, upsert_profile


def create_profiles_from_answers(
    answers: dict[str, Any],
    *,
    local_root: Path = DEFAULT_LOCAL_ROOT,
    db_path: Path = DEFAULT_DB_PATH,
) -> dict[str, Path]:
    paths = build_profiles_from_answers(answers, local_root)
    upsert_profile("users", answers["user_id"], _load_json(paths["user"]), db_path)
    upsert_profile(
        "experiments", answers["experiment_template_id"], _load_json(paths["experiment"]), db_path
    )
    upsert_profile("instruments", answers["instrument_id"], _load_json(paths["instrument"]), db_path)
    return paths


def _load_json(path: Path) -> dict[str, Any]:
    import json

    return json.loads(path.read_text(encoding="utf-8"))


def analyze_wet_record(record: dict[str, Any], effective_profile: dict[str, Any]) -> dict[str, Any]:
    present_fields = _collect_present_fields(record)
    aliases = effective_profile.get("term_aliases", {})
    normalized_steps = _collect_normalized_steps(record, aliases)
    required_fields = effective_profile.get("required_fields", [])
    missing_fields = [field for field in required_fields if field not in present_fields]
    review_issues = [
        {
            "severity": "warning",
            "title": "个性化必填字段缺失",
            "detail": f"缺少字段：{field}",
            "field": field,
        }
        for field in missing_fields
    ]
    payload = {
        "experiment_id": record.get("experiment_id"),
        "profile_context": effective_profile.get("profile_context", {}),
        "present_fields": sorted(present_fields),
        "missing_required_fields": missing_fields,
        "normalized_steps": normalized_steps,
        "review_issues": review_issues,
        "effective_profile": effective_profile,
    }
    return payload


def analyze_and_store(
    record: dict[str, Any],
    *,
    user_id: str | None = None,
    experiment_template_id: str | None = None,
    instrument_id: str | None = None,
    group_id: str = "materials_default",
    local_root: Path = DEFAULT_LOCAL_ROOT,
    db_path: Path = DEFAULT_DB_PATH,
) -> dict[str, Any]:
    profile = load_effective_profile(
        user_id=user_id,
        experiment_template_id=experiment_template_id,
        instrument_id=instrument_id,
        group_id=group_id,
        local_root=local_root,
    )
    payload = analyze_wet_record(record, profile)
    payload["analysis_run_id"] = save_analysis_run(payload, record.get("experiment_id"), db_path)
    return payload


def _collect_present_fields(record: dict[str, Any]) -> set[str]:
    fields: set[str] = set()
    for scalar in ("experiment_id", "operator", "project_id", "group_id", "title"):
        if record.get(scalar) not in (None, "", []):
            fields.add(scalar)
    if record.get("sample_id"):
        fields.add("sample_id")
    if record.get("materials") or record.get("materials_catalog"):
        fields.add("materials")
    if record.get("steps") or record.get("events"):
        fields.add("protocol_steps")
    if record.get("measurements"):
        fields.add("measurements")
    for page in record.get("pages", []) or []:
        if page.get("sample_id"):
            fields.add("sample_id")
        if page.get("extracted_materials"):
            fields.add("materials")
        if page.get("extracted_steps") or page.get("extracted_events"):
            fields.add("protocol_steps")
        fields.update((page.get("extracted_facts") or {}).keys())
    return fields


def _collect_normalized_steps(record: dict[str, Any], aliases: dict[str, str]) -> list[dict[str, Any]]:
    steps: list[dict[str, Any]] = []
    raw_steps = list(record.get("steps", []) or [])
    for page in record.get("pages", []) or []:
        raw_steps.extend(page.get("extracted_steps", []) or [])
        raw_steps.extend(page.get("extracted_events", []) or [])
    raw_steps.extend(record.get("events", []) or [])
    for raw in raw_steps:
        raw_type = raw.get("step_type") or raw.get("action_type") or "other"
        canonical = aliases.get(raw_type, raw_type)
        steps.append(
            {
                "raw_step_type": raw_type,
                "normalized_step_type": canonical,
                "description": raw.get("description"),
            }
        )
    return steps
