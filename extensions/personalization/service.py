from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .config import (
    DEFAULT_LOCAL_ROOT,
    TEMPLATE_ROOT,
    build_profiles_from_answers,
    load_effective_profile,
    local_profile_path,
    save_local_profile,
)
from .repository import DEFAULT_DB_PATH, save_analysis_run, upsert_profile

EDITABLE_USER_PROFILE_FIELDS = {
    "display_name",
    "term_aliases",
    "sample_id_patterns",
    "preferred_fields",
    "required_fields",
    "handwriting_notes",
}


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
    return json.loads(path.read_text(encoding="utf-8"))


def list_user_profiles(*, local_root: Path = DEFAULT_LOCAL_ROOT) -> list[dict[str, Any]]:
    users_root = local_root / "users"
    if not users_root.exists():
        return []
    profiles: list[dict[str, Any]] = []
    for path in sorted(users_root.glob("*.json")):
        payload = _safe_read_json(path)
        if not payload:
            continue
        user_id = payload.get("user_id") or path.stem
        profiles.append(
            {
                "user_id": user_id,
                "display_name": payload.get("display_name") or user_id,
                "term_alias_count": len(payload.get("term_aliases", {})),
                "required_fields": payload.get("required_fields", []),
                "preferred_fields": payload.get("preferred_fields", []),
            }
        )
    return profiles


def get_user_profile(
    user_id: str,
    *,
    local_root: Path = DEFAULT_LOCAL_ROOT,
) -> dict[str, Any] | None:
    path = local_profile_path("users", user_id, local_root)
    payload = _safe_read_json(path)
    if not payload:
        return None
    payload["user_id"] = payload.get("user_id") or user_id
    payload["display_name"] = payload.get("display_name") or user_id
    return payload


def save_user_profile(
    user_id: str,
    updates: dict[str, Any],
    *,
    local_root: Path = DEFAULT_LOCAL_ROOT,
    db_path: Path = DEFAULT_DB_PATH,
) -> dict[str, Any]:
    unexpected = set(updates) - EDITABLE_USER_PROFILE_FIELDS
    if unexpected:
        raise ValueError(f"Unsupported user profile fields: {', '.join(sorted(unexpected))}")

    current = get_user_profile(user_id, local_root=local_root) or {
        "user_id": user_id,
        "display_name": user_id,
        "term_aliases": {},
        "sample_id_patterns": [],
        "preferred_fields": [],
        "required_fields": [],
        "handwriting_notes": [],
    }
    payload = {**current, **updates, "user_id": user_id}
    payload["display_name"] = payload.get("display_name") or user_id
    save_local_profile("users", user_id, payload, local_root)
    upsert_profile("users", user_id, payload, db_path)
    return payload


def list_available_templates(*, local_root: Path = DEFAULT_LOCAL_ROOT) -> dict[str, list[dict[str, Any]]]:
    return {
        "groups": _list_template_family("groups", local_root=local_root),
        "experiments": _list_template_family("experiments", local_root=local_root),
        "instruments": _list_template_family("instruments", local_root=local_root),
    }


def summarize_effective_profile(
    *,
    user_id: str | None = None,
    experiment_template_id: str | None = None,
    instrument_id: str | None = None,
    group_id: str = "materials_default",
    local_root: Path = DEFAULT_LOCAL_ROOT,
) -> dict[str, Any]:
    profile = load_effective_profile(
        user_id=user_id,
        experiment_template_id=experiment_template_id,
        instrument_id=instrument_id,
        group_id=group_id,
        local_root=local_root,
    )
    required_fields = profile.get("required_fields", [])
    preferred_fields = profile.get("preferred_fields", [])
    aliases = profile.get("term_aliases", {})
    alias_examples = [
        {"raw": raw, "canonical": canonical}
        for raw, canonical in sorted(aliases.items())[:8]
    ]
    messages = [
        _render_required_fields_message(required_fields),
        _render_alias_message(aliases),
    ]
    if preferred_fields:
        messages.append(f"额外关注字段：{'、'.join(preferred_fields)}。")
    if profile.get("sample_id_patterns"):
        messages.append(f"样品编号模式：{'、'.join(profile['sample_id_patterns'])}。")
    return {
        "profile_context": profile.get("profile_context", {}),
        "required_fields": required_fields,
        "preferred_fields": preferred_fields,
        "sample_id_patterns": profile.get("sample_id_patterns", []),
        "focus_parameters": profile.get("focus_parameters", []),
        "term_alias_examples": alias_examples,
        "messages": messages,
        "layers": _describe_loaded_layers(
            user_id=user_id,
            experiment_template_id=experiment_template_id,
            instrument_id=instrument_id,
            group_id=group_id,
            local_root=local_root,
        ),
    }


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


def _safe_read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def _list_template_family(
    family: str,
    *,
    local_root: Path,
) -> list[dict[str, Any]]:
    id_fields = {
        "groups": "group_id",
        "experiments": "template_id",
        "instruments": "instrument_id",
    }
    entries: dict[str, dict[str, Any]] = {}
    for origin, root in (
        ("shared", TEMPLATE_ROOT / family),
        ("local", local_root / family),
    ):
        if not root.exists():
            continue
        for path in sorted(root.glob("*.json")):
            payload = _safe_read_json(path)
            if not payload:
                continue
            item_id = payload.get(id_fields[family]) or path.stem
            current = entries.get(item_id, {})
            entries[item_id] = {
                "id": item_id,
                "display_name": payload.get("display_name") or item_id,
                "origin": origin if not current else "shared+local",
                "technique": payload.get("technique"),
            }
    return [entries[key] for key in sorted(entries)]


def _render_required_fields_message(required_fields: list[str]) -> str:
    if not required_fields:
        return "当前没有额外必填字段。"
    return f"当前会检查 {len(required_fields)} 个必填字段：{'、'.join(required_fields)}。"


def _render_alias_message(aliases: dict[str, str]) -> str:
    if not aliases:
        return "当前未启用术语归一规则。"
    return f"当前启用 {len(aliases)} 条术语归一规则。"


def _describe_loaded_layers(
    *,
    user_id: str | None,
    experiment_template_id: str | None,
    instrument_id: str | None,
    group_id: str,
    local_root: Path,
) -> list[dict[str, Any]]:
    return [
        {
            "kind": "default",
            "label": "默认规则",
            "id": "defaults",
            "loaded": (TEMPLATE_ROOT / "defaults.json").exists(),
        },
        {
            "kind": "group",
            "label": "课题组模板",
            "id": group_id,
            "loaded": (TEMPLATE_ROOT / "groups" / f"{group_id}.json").exists(),
        },
        {
            "kind": "experiment",
            "label": "实验模板",
            "id": experiment_template_id,
            "loaded": bool(
                experiment_template_id
                and (
                    (TEMPLATE_ROOT / "experiments" / f"{experiment_template_id}.json").exists()
                    or local_profile_path("experiments", experiment_template_id, local_root).exists()
                )
            ),
        },
        {
            "kind": "instrument",
            "label": "仪器模板",
            "id": instrument_id,
            "loaded": bool(
                instrument_id
                and (
                    (TEMPLATE_ROOT / "instruments" / f"{instrument_id}.json").exists()
                    or local_profile_path("instruments", instrument_id, local_root).exists()
                )
            ),
        },
        {
            "kind": "user",
            "label": "个人覆盖",
            "id": user_id,
            "loaded": bool(user_id and local_profile_path("users", user_id, local_root).exists()),
        },
    ]


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
