from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .config import DEFAULT_LOCAL_ROOT, load_effective_profile
from .repository import DEFAULT_DB_PATH
from .service import analyze_and_store, create_profiles_from_answers


def _split_csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def _split_mapping(value: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for item in _split_csv(value):
        if "=" not in item:
            continue
        key, mapped = item.split("=", 1)
        if key.strip() and mapped.strip():
            result[key.strip()] = mapped.strip()
    return result


def _prompt_answers() -> dict[str, Any]:
    return {
        "user_id": input("用户 ID: ").strip(),
        "display_name": input("用户显示名: ").strip(),
        "user_term_aliases": _split_mapping(input("用户术语别名 raw=canonical，逗号分隔: ")),
        "sample_id_patterns": _split_csv(input("样品编号模式，逗号分隔: ")),
        "user_preferred_fields": _split_csv(input("常写字段，逗号分隔: ")),
        "user_required_fields": _split_csv(input("个人必填字段，逗号分隔: ")),
        "handwriting_notes": _split_csv(input("手写习惯备注，逗号分隔: ")),
        "experiment_template_id": input("实验模板 ID: ").strip(),
        "experiment_display_name": input("实验模板显示名: ").strip(),
        "experiment_required_fields": _split_csv(input("实验模板必填字段，逗号分隔: ")),
        "experiment_preferred_fields": _split_csv(input("实验模板关注字段，逗号分隔: ")),
        "common_step_types": _split_csv(input("常见步骤类型，逗号分隔: ")),
        "experiment_term_aliases": _split_mapping(input("实验术语别名 raw=canonical，逗号分隔: ")),
        "instrument_id": input("仪器模板 ID: ").strip(),
        "instrument_display_name": input("仪器显示名: ").strip(),
        "technique": input("仪器技术类型: ").strip(),
        "file_patterns": _split_csv(input("仪器文件模式，逗号分隔: ")),
        "field_mappings": _split_mapping(input("字段映射 raw=canonical，逗号分隔: ")),
        "focus_parameters": _split_csv(input("仪器关注参数，逗号分隔: ")),
    }


def _load_answers(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Wet-lab personalization add-on CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    wizard = sub.add_parser("wizard", help="Create user / experiment / instrument profiles")
    wizard.add_argument("--answers-json", type=Path)
    wizard.add_argument("--local-root", type=Path, default=DEFAULT_LOCAL_ROOT)
    wizard.add_argument("--db-path", type=Path, default=DEFAULT_DB_PATH)

    show = sub.add_parser("show-effective", help="Render merged effective profile")
    show.add_argument("--user-id")
    show.add_argument("--experiment-template")
    show.add_argument("--instrument-template")
    show.add_argument("--group-id", default="materials_default")
    show.add_argument("--local-root", type=Path, default=DEFAULT_LOCAL_ROOT)

    parse = sub.add_parser("parse", help="Analyze a wet-lab record with personalized rules")
    parse.add_argument("--input", type=Path, required=True)
    parse.add_argument("--user-id")
    parse.add_argument("--experiment-template")
    parse.add_argument("--instrument-template")
    parse.add_argument("--group-id", default="materials_default")
    parse.add_argument("--local-root", type=Path, default=DEFAULT_LOCAL_ROOT)
    parse.add_argument("--db-path", type=Path, default=DEFAULT_DB_PATH)
    parse.add_argument("--output", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "wizard":
        answers = _load_answers(args.answers_json) if args.answers_json else _prompt_answers()
        paths = create_profiles_from_answers(
            answers, local_root=args.local_root, db_path=args.db_path
        )
        print(json.dumps({k: str(v) for k, v in paths.items()}, ensure_ascii=False, indent=2))
        return 0
    if args.command == "show-effective":
        payload = load_effective_profile(
            user_id=args.user_id,
            experiment_template_id=args.experiment_template,
            instrument_id=args.instrument_template,
            group_id=args.group_id,
            local_root=args.local_root,
        )
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0
    record = json.loads(args.input.read_text(encoding="utf-8"))
    payload = analyze_and_store(
        record,
        user_id=args.user_id,
        experiment_template_id=args.experiment_template,
        instrument_id=args.instrument_template,
        group_id=args.group_id,
        local_root=args.local_root,
        db_path=args.db_path,
    )
    rendered = json.dumps(payload, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
