"""Verify ExperimentOrchestrator dispatches VLM page analyses concurrently."""
from __future__ import annotations

import threading
import time

from sci_data_logger.schemas import DraftExperimentRequest, PagePacket
from sci_data_logger.services.orchestrator import ExperimentOrchestrator


class _BlockingDocumentProcessor:
    """Fake DocumentProcessor whose analyze_page blocks until released.

    Tracks peak concurrency observed across all in-flight calls.
    """

    def __init__(self, release: threading.Event) -> None:
        self.release = release
        self._lock = threading.Lock()
        self._in_flight = 0
        self.peak_in_flight = 0

    def analyze_page(self, path):
        with self._lock:
            self._in_flight += 1
            if self._in_flight > self.peak_in_flight:
                self.peak_in_flight = self._in_flight
        try:
            # Block until the test releases, so multiple calls can stack up.
            assert self.release.wait(timeout=5.0), "release event never fired"
        finally:
            with self._lock:
                self._in_flight -= 1
        return PagePacket(source_path=str(path))

    def analyze_pages(self, path):
        return [self.analyze_page(path)]


def test_orchestrator_dispatches_pages_concurrently(tmp_path):
    images = []
    for i in range(4):
        p = tmp_path / f"page_{i}.jpg"
        p.write_bytes(b"x")
        images.append(p)

    release = threading.Event()
    proc = _BlockingDocumentProcessor(release)
    orch = ExperimentOrchestrator(document_processor=proc)

    result: dict = {}

    def _run():
        result["record"] = orch.create_draft(
            DraftExperimentRequest(experiment_id="EXP-CONC", image_paths=images)
        )

    t = threading.Thread(target=_run)
    t.start()
    # Wait long enough for the worker pool to stack pages up.
    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline and proc.peak_in_flight < 2:
        time.sleep(0.02)
    release.set()
    t.join(timeout=5.0)
    assert not t.is_alive(), "orchestrator did not finish"

    # With vlm_concurrency default = 4 and 4 images we expect at least 2 in flight.
    assert proc.peak_in_flight >= 2
    assert len(result["record"].pages) == 4


def test_orchestrator_falls_back_to_sequential_when_concurrency_one(tmp_path, monkeypatch):
    """max_workers <= 1 should bypass the executor (deterministic ordering)."""
    from sci_data_logger.config import get_settings

    get_settings.cache_clear()  # type: ignore[attr-defined]
    monkeypatch.setenv("SCI_DATA_LOGGER_VLM_CONCURRENCY", "1")

    images = []
    for i in range(3):
        p = tmp_path / f"p{i}.jpg"
        p.write_bytes(b"x")
        images.append(p)

    seen_order: list[str] = []

    class _Sequential:
        def analyze_page(self, path):
            seen_order.append(str(path))
            return PagePacket(source_path=str(path))

        def analyze_pages(self, path):
            return [self.analyze_page(path)]

    try:
        orch = ExperimentOrchestrator(document_processor=_Sequential())
        rec = orch.create_draft(
            DraftExperimentRequest(experiment_id="EXP-SEQ", image_paths=images)
        )
    finally:
        monkeypatch.delenv("SCI_DATA_LOGGER_VLM_CONCURRENCY", raising=False)
        get_settings.cache_clear()  # type: ignore[attr-defined]

    assert seen_order == [str(p) for p in images]
    assert [p.source_path for p in rec.pages] == [str(p) for p in images]
