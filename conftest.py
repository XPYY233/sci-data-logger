"""Pytest root config: ensure worktree's ``src/`` shadows any editable install.

Without this, an editable ``sci-data-logger`` install from the parent repo
takes precedence and tests run against stale code rather than the local
worktree changes.
"""
from __future__ import annotations

import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parent / "src"
if _SRC.exists():
    sys.path.insert(0, str(_SRC))
