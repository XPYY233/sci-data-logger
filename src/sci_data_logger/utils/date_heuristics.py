"""Best-effort date_label -> ISO 8601 推断。失败返回 None，不抛异常。"""
from __future__ import annotations

import re
from datetime import datetime

_MD_PATTERN = re.compile(r"^(\d{1,2})[./-](\d{1,2})$")
_YMD_PATTERN = re.compile(r"^(\d{4})[./-](\d{1,2})[./-](\d{1,2})$")


def label_to_iso(label: str | None, default_year: int | None = None) -> str | None:
    """Convert date label tokens like '5.20' or '2026.5.20' into ISO 'YYYY-MM-DD'.

    Returns None if the label can't be parsed.
    """
    if not label:
        return None
    s = str(label).strip()
    if not s:
        return None

    m = _YMD_PATTERN.match(s)
    if m:
        y, mo, d = (int(x) for x in m.groups())
    else:
        m = _MD_PATTERN.match(s)
        if not m:
            return None
        mo, d = (int(x) for x in m.groups())
        y = default_year or datetime.now().year

    try:
        return datetime(y, mo, d).strftime("%Y-%m-%d")
    except ValueError:
        return None
