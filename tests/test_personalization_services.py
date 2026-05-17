from __future__ import annotations

import json
from pathlib import Path

from extensions.personalization.repository import connect
from extensions.personalization.service import (
    get_user_profile,
    list_available_templates,
    list_user_profiles,
    save_user_profile,
    summarize_effective_profile,
)


def test_user_profile_crud_syncs_json_and_sidecar_db(tmp_path: Path) -> None:
    db_path = tmp_path / "personalization.db"

    saved = save_user_profile(
        "alice",
        {
            "display_name": "Alice",
            "term_aliases": {"预烧": "calcine"},
            "sample_id_patterns": ["A-{seq}"],
            "preferred_fields": ["atmosphere"],
            "required_fields": ["temperature"],
            "handwriting_notes": ["7 容易写得像 1"],
        },
        local_root=tmp_path,
        db_path=db_path,
    )

    assert saved["display_name"] == "Alice"
    assert get_user_profile("alice", local_root=tmp_path) == saved
    assert list_user_profiles(local_root=tmp_path)[0]["user_id"] == "alice"

    payload = json.loads((tmp_path / "users" / "alice.json").read_text(encoding="utf-8"))
    assert payload["term_aliases"]["预烧"] == "calcine"

    with connect(db_path) as conn:
        row = conn.execute(
            "SELECT payload_json FROM profiles WHERE profile_type='users' AND profile_id='alice'"
        ).fetchone()
    assert row is not None
    assert json.loads(row["payload_json"])["display_name"] == "Alice"


def test_template_listing_includes_shared_and_local_overrides(tmp_path: Path) -> None:
    (tmp_path / "experiments").mkdir(parents=True)
    (tmp_path / "experiments" / "custom_exp.json").write_text(
        json.dumps({"template_id": "custom_exp", "display_name": "自定义实验"}, ensure_ascii=False),
        encoding="utf-8",
    )

    templates = list_available_templates(local_root=tmp_path)

    assert any(item["id"] == "materials_default" for item in templates["groups"])
    assert any(item["id"] == "solid_state_synthesis" for item in templates["experiments"])
    assert any(item["id"] == "custom_exp" for item in templates["experiments"])
    assert any(item["id"] == "generic_xrd" for item in templates["instruments"])


def test_effective_profile_summary_is_human_readable(tmp_path: Path) -> None:
    save_user_profile(
        "alice",
        {
            "display_name": "Alice",
            "term_aliases": {"一烧": "calcine_stage_1"},
            "required_fields": ["atmosphere"],
        },
        local_root=tmp_path,
        db_path=tmp_path / "personalization.db",
    )

    summary = summarize_effective_profile(
        user_id="alice",
        experiment_template_id="solid_state_synthesis",
        local_root=tmp_path,
    )

    assert "atmosphere" in summary["required_fields"]
    assert any("必填字段" in message for message in summary["messages"])
    assert any(item["raw"] == "一烧" for item in summary["term_alias_examples"])
    assert summary["layers"][-1]["loaded"] is True
