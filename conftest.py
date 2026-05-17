"""Pytest root config: ensure worktree's ``src/`` shadows any editable install.

Without this, an editable ``sci-data-logger`` install from the parent repo
takes precedence and tests run against stale code rather than the local
worktree changes.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_SRC = Path(__file__).resolve().parent / "src"
if _SRC.exists():
    sys.path.insert(0, str(_SRC))


@pytest.fixture
def fake_doc_processor():
    """Shared factory for a DocumentProcessor stub.

    Returns a callable ``make(pages)`` that yields a fake exposing both
    ``analyze_page`` and ``analyze_pages`` (FIFO over the pre-supplied
    PagePacket list). Both methods accept an optional ``prev_tail`` kwarg
    so the fake plugs into both legacy and context-hint code paths.

    Use this in new tests instead of redefining `_FakeDocumentProcessor`
    inline. Existing tests keep their inline fakes — no churn migration.
    """
    from sci_data_logger.schemas import PagePacket

    class _FakeDocumentProcessor:
        def __init__(self, pages):
            self._pages = list(pages)

        def analyze_page(self, path, prev_tail=None):
            return self._pages.pop(0) if self._pages else PagePacket(source_path=str(path))

        def analyze_pages(self, path, prev_tail=None):
            return [self.analyze_page(path, prev_tail)]

    def _factory(pages):
        return _FakeDocumentProcessor(pages)

    return _factory
