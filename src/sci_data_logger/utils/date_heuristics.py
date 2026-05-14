"""Best-effort date_label -> ISO 8601 推断。失败返回 None，不抛异常。"""
from __future__ import annotations

import re
from datetime import datetime

_MD_PATTERN = re.compile(r"^(\d{1,2})[./-](\d{1,2})$")
_YMD_PATTERN = re.compile(r"^(\d{4})[./-](\d{1,2})[./-](\d{1,2})$")


def label_to_iso(label: str | None, default_year: int | None = None) -> str | None:
    """Convert date label tokens like '5.20' or '2026.5.20' into ISO 'YYYY-MM-DD'.

    Returns None if the label can't be parsed, or if only M/D was found and
    ``default_year`` is None (caller must supply a year — we do NOT fall back
    to ``datetime.now().year`` because the parse year can differ from the
    notebook's actual year).
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
        if default_year is None:
            return None
        mo, d = (int(x) for x in m.groups())
        y = default_year

    try:
        return datetime(y, mo, d).strftime("%Y-%m-%d")
    except ValueError:
        return None


def infer_default_year(date_labels: list[str | None]) -> int | None:
    """Scan a list of date label strings and return the first full YMD year found."""
    for label in date_labels:
        if not label:
            continue
        s = str(label).strip()
        if not s:
            continue
        m = _YMD_PATTERN.match(s)
        if m:
            try:
                return int(m.group(1))
            except ValueError:
                continue
    return None
