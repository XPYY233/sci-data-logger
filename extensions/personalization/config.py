from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

from .models import ExperimentTemplate, InstrumentTemplate, UserProfile

PACKAGE_ROOT = Path(__file__).resolve().parent
TEMPLATE_ROOT = PACKAGE_ROOT / "templates"
DEFAULT_LOCAL_ROOT = Path(".local_data/extensions/personalization")


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _merge_unique(*values: list[str] | None) -> list[str]:
    merged: list[str] = []
    for items in values:
        for item in items or []:
            if item and item not in merged:
                merged.append(item)
    return merged


def _merge_profile(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(base)
    for key, value in overlay.items():
        if value is None:
            continue
        if key in {"term_aliases", "field_mappings"}:
            result[key] = {**result.get(key, {}), **value}
        elif key in {
            "sample_id_patterns",
            "required_fields",
            "preferred_fields",
            "common_step_types",
            "file_patterns",
            "focus_parameters",
            "handwriting_notes",
        }:
            result[key] = _merge_unique(result.get(key, []), value)
        elif key == "metadata":
            result[key] = {**result.get(key, {}), **value}
    return result


def local_profile_path(profile_type: str, profile_id: str, local_root: Path = DEFAULT_LOCAL_ROOT) -> Path:
    return local_root / profile_type / f"{profile_id}.json"


def save_local_profile(
    profile_type: str,
    profile_id: str,
    payload: dict[str, Any],
    local_root: Path = DEFAULT_LOCAL_ROOT,
) -> Path:
    return _write_json(local_profile_path(profile_type, profile_id, local_root), payload)


def build_profiles_from_answers(
    answers: dict[str, Any],
    local_root: Path = DEFAULT_LOCAL_ROOT,
) -> dict[str, Path]:
    user = UserProfile(
        user_id=answers["user_id"],
        display_name=answers.get("display_name") or answers["user_id"],
        term_aliases=answers.get("user_term_aliases", {}),
        sample_id_patterns=answers.get("sample_id_patterns", []),
        preferred_fields=answers.get("user_preferred_fields", []),
        required_fields=answers.get("user_required_fields", []),
        handwriting_notes=answers.get("handwriting_notes", []),
    )
    experiment = ExperimentTemplate(
        template_id=answers["experiment_template_id"],
        display_name=answers.get("experiment_display_name") or answers["experiment_template_id"],
        required_fields=answers.get("experiment_required_fields", []),
        preferred_fields=answers.get("experiment_preferred_fields", []),
        common_step_types=answers.get("common_step_types", []),
        term_aliases=answers.get("experiment_term_aliases", {}),
    )
    instrument = InstrumentTemplate(
        instrument_id=answers["instrument_id"],
        display_name=answers.get("instrument_display_name") or answers["instrument_id"],
        technique=answers.get("technique") or "other",
        file_patterns=answers.get("file_patterns", []),
        field_mappings=answers.get("field_mappings", {}),
        focus_parameters=answers.get("focus_parameters", []),
    )
    return {
        "user": save_local_profile("users", user.user_id, user.to_dict(), local_root),
        "experiment": save_local_profile(
            "experiments", experiment.template_id, experiment.to_dict(), local_root
        ),
        "instrument": save_local_profile(
            "instruments", instrument.instrument_id, instrument.to_dict(), local_root
        ),
    }


def load_effective_profile(
    *,
    user_id: str | None = None,
    experiment_template_id: str | None = None,
    instrument_id: str | None = None,
    group_id: str = "materials_default",
    local_root: Path = DEFAULT_LOCAL_ROOT,
) -> dict[str, Any]:
    result = _read_json(TEMPLATE_ROOT / "defaults.json")
    result = _merge_profile(result, _read_json(TEMPLATE_ROOT / "groups" / f"{group_id}.json"))
    if experiment_template_id:
        result = _merge_profile(
            result, _read_json(TEMPLATE_ROOT / "experiments" / f"{experiment_template_id}.json")
        )
        result = _merge_profile(
            result,
            _read_json(local_profile_path("experiments", experiment_template_id, local_root)),
        )
    if instrument_id:
        result = _merge_profile(
            result, _read_json(TEMPLATE_ROOT / "instruments" / f"{instrument_id}.json")
        )
        result = _merge_profile(
            result, _read_json(local_profile_path("instruments", instrument_id, local_root))
        )
    if user_id:
        result = _merge_profile(result, _read_json(local_profile_path("users", user_id, local_root)))
    result["profile_context"] = {
        "group_id": group_id,
        "experiment_template_id": experiment_template_id,
        "instrument_id": instrument_id,
        "user_id": user_id,
    }
    return result
