from __future__ import annotations

import json
from typing import Any


JSON_PARSE_WARNING = "未能从模型输出中解析 JSON。"


def parse_first_json_object(text: str) -> dict[str, Any]:
    """Parse the first JSON object embedded in model output."""

    stripped = text.strip()
    try:
        parsed = json.loads(stripped)
        return parsed if isinstance(parsed, dict) else {"value": parsed}
    except json.JSONDecodeError:
        pass

    decoder = json.JSONDecoder()
    start = stripped.find("{")
    while start != -1:
        try:
            parsed, _ = decoder.raw_decode(stripped[start:])
            return parsed if isinstance(parsed, dict) else {"value": parsed}
        except json.JSONDecodeError:
            start = stripped.find("{", start + 1)
    return {
        "raw_text": text,
        "_parse_error": "no_json_object",
        "warnings": [JSON_PARSE_WARNING],
        "open_questions": ["请人工检查 VLM 原始输出并补录结构化字段。"],
        "review_required": True,
    }
