from __future__ import annotations

from pathlib import Path

from sci_data_logger.config import get_settings
from sci_data_logger.prompts import with_context_hint
from sci_data_logger.schemas import DraftExperimentRequest, PagePacket
from sci_data_logger.services.document import (
    DocumentProcessor,
    _tail_of_text_blocks,
)
from sci_data_logger.services.orchestrator import ExperimentOrchestrator


class _CapturingVLMClient:
    """Records the prompt string each call receives."""

    def __init__(self) -> None:
        self.captured_prompts: list[str] = []

    def analyze_image(self, image_path: Path, prompt: str) -> dict[str, object]:
        self.captured_prompts.append(prompt)
        return {
            "raw_text": "<mock>",
            "json": {
                "page_type": ["synthesis_note"],
                "materials": [],
                "steps": [],
                "observations": [],
                "instruments": [],
                "text_blocks": [],
                "table_blocks": [],
                "extracted_facts": {},
                "open_questions": [],
                "warnings": [],
                "review_required": False,
            },
            "model": "fake",
            "usage": None,
        }


def test_with_context_hint_returns_original_when_tail_empty() -> None:
    assert with_context_hint("BODY", None) == "BODY"
    assert with_context_hint("BODY", "") == "BODY"


def test_with_context_hint_prepends_when_tail_present() -> None:
    out = with_context_hint("BODY", "  PREV TAIL  ")
    assert "PREV TAIL" in out
    assert "BODY" in out
    # tail appears before body
    assert out.index("PREV TAIL") < out.index("BODY")


def test_tail_of_text_blocks_concatenates_and_truncates() -> None:
    # joined = "AAAA\nBBBB" → last 5 chars = "\nBBBB"
    joined = "AAAA\nBBBB"
    assert _tail_of_text_blocks(["AAAA", "BBBB"], 5) == joined[-5:]


def test_tail_of_text_blocks_empty_input_returns_empty() -> None:
    assert _tail_of_text_blocks([], 10) == ""
    assert _tail_of_text_blocks(["", ""], 10) == ""


def test_document_processor_threads_prev_tail_when_enabled(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("SCI_DATA_LOGGER_CONTEXT_HINT_ENABLED", "true")
    get_settings.cache_clear()

    image_path = tmp_path / "page.jpg"
    image_path.write_bytes(b"fake image")

    capturing = _CapturingVLMClient()
    dp = DocumentProcessor(vlm_client=capturing)
    dp.analyze_page(image_path, prev_tail="球磨结束")

    assert capturing.captured_prompts, "VLM client was not invoked"
    assert "球磨结束" in capturing.captured_prompts[0]

    get_settings.cache_clear()


def test_document_processor_ignores_prev_tail_when_disabled(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.delenv("SCI_DATA_LOGGER_CONTEXT_HINT_ENABLED", raising=False)
    get_settings.cache_clear()

    image_path = tmp_path / "page.jpg"
    image_path.write_bytes(b"fake image")

    capturing = _CapturingVLMClient()
    dp = DocumentProcessor(vlm_client=capturing)
    dp.analyze_page(image_path, prev_tail="should not appear")

    assert capturing.captured_prompts, "VLM client was not invoked"
    assert "should not appear" not in capturing.captured_prompts[0]

    get_settings.cache_clear()


class _RecordingDocumentProcessor:
    """DocumentProcessor stub that records the prev_tail passed for each call."""

    def __init__(self, pages_per_call: list[list[PagePacket]]) -> None:
        self._pages_per_call = list(pages_per_call)
        self.calls: list[str | None] = []

    def analyze_pages(
        self, source_path: Path, prev_tail: str | None = None
    ) -> list[PagePacket]:
        self.calls.append(prev_tail)
        return self._pages_per_call.pop(0)


def test_orchestrator_sequential_path_threads_context_between_pages(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("SCI_DATA_LOGGER_VLM_CONCURRENCY", "1")
    monkeypatch.setenv("SCI_DATA_LOGGER_CONTEXT_HINT_ENABLED", "true")
    monkeypatch.setenv("SCI_DATA_LOGGER_CONTEXT_HINT_TAIL_CHARS", "400")
    get_settings.cache_clear()

    img1 = tmp_path / "p1.jpg"
    img1.write_bytes(b"x")
    img2 = tmp_path / "p2.jpg"
    img2.write_bytes(b"x")

    page1 = PagePacket(
        source_path=str(img1),
        text_blocks=["第一页开头", "第一页结尾片段-球磨结束"],
    )
    page2 = PagePacket(source_path=str(img2), text_blocks=["第二页内容"])

    fake_dp = _RecordingDocumentProcessor([[page1], [page2]])
    orch = ExperimentOrchestrator(document_processor=fake_dp)
    orch.create_draft(
        DraftExperimentRequest(
            experiment_id="EXP-CTX-001", image_paths=[img1, img2]
        )
    )

    assert len(fake_dp.calls) == 2
    # first page: no predecessor
    assert fake_dp.calls[0] is None
    # second page: non-empty tail derived from page 1's text_blocks
    assert fake_dp.calls[1] is not None
    assert "球磨结束" in fake_dp.calls[1]

    get_settings.cache_clear()


class _SequentialityRecordingDocumentProcessor:
    """Records prev_tail + per-call timestamps so we can assert strict ordering."""

    def __init__(self, pages_per_call: list[list[PagePacket]]) -> None:
        self._pages_per_call = list(pages_per_call)
        self.prev_tails: list[str | None] = []
        self.call_intervals: list[tuple[float, float]] = []

    def analyze_pages(
        self, source_path: Path, prev_tail: str | None = None
    ) -> list[PagePacket]:
        import time

        start = time.perf_counter()
        # Tiny sleep so overlapping concurrent calls would be detectable.
        time.sleep(0.01)
        self.prev_tails.append(prev_tail)
        end = time.perf_counter()
        self.call_intervals.append((start, end))
        return self._pages_per_call.pop(0)


def test_context_hint_forces_sequential_even_with_high_vlm_concurrency(
    tmp_path: Path, monkeypatch
) -> None:
    """When context hint is enabled, vlm_concurrency=8 must NOT spawn parallel calls."""
    monkeypatch.setenv("SCI_DATA_LOGGER_VLM_CONCURRENCY", "8")
    monkeypatch.setenv("SCI_DATA_LOGGER_CONTEXT_HINT_ENABLED", "true")
    monkeypatch.setenv("SCI_DATA_LOGGER_CONTEXT_HINT_TAIL_CHARS", "400")
    get_settings.cache_clear()

    img1 = tmp_path / "p1.jpg"
    img1.write_bytes(b"x")
    img2 = tmp_path / "p2.jpg"
    img2.write_bytes(b"x")
    img3 = tmp_path / "p3.jpg"
    img3.write_bytes(b"x")

    page1 = PagePacket(
        source_path=str(img1), text_blocks=["页1开头", "页1结尾-A"]
    )
    page2 = PagePacket(
        source_path=str(img2), text_blocks=["页2开头", "页2结尾-B"]
    )
    page3 = PagePacket(source_path=str(img3), text_blocks=["页3"])

    fake_dp = _SequentialityRecordingDocumentProcessor([[page1], [page2], [page3]])
    orch = ExperimentOrchestrator(document_processor=fake_dp)
    orch.create_draft(
        DraftExperimentRequest(
            experiment_id="EXP-CTX-CONCURRENCY",
            image_paths=[img1, img2, img3],
        )
    )

    # (a) prev_tail chain is correct: None → tail-of-page1 → tail-of-page2.
    assert len(fake_dp.prev_tails) == 3
    assert fake_dp.prev_tails[0] is None
    assert fake_dp.prev_tails[1] is not None
    assert "页1结尾-A" in fake_dp.prev_tails[1]
    assert fake_dp.prev_tails[2] is not None
    assert "页2结尾-B" in fake_dp.prev_tails[2]

    # (b) calls are strictly sequential — each start >= previous end (no overlap).
    starts = [s for s, _ in fake_dp.call_intervals]
    ends = [e for _, e in fake_dp.call_intervals]
    assert starts == sorted(starts), "call start times not monotonic"
    for i in range(1, len(fake_dp.call_intervals)):
        assert starts[i] >= ends[i - 1], (
            f"call {i} started before call {i - 1} finished — concurrency leaked"
        )

    get_settings.cache_clear()
