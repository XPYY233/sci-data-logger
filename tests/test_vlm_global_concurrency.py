"""Process-wide VLM dispatch chokepoint.

Without this cap, 40 starlette threadpool workers × 4 orchestrator workers =
160 simultaneous DashScope requests, quota-blasting and socket-starving the
host. The semaphore guarantees at most `vlm_global_concurrency` HTTP calls
are in flight regardless of how many FastAPI requests are queued.
"""
from __future__ import annotations

import threading
import time

import pytest

from sci_data_logger.config import Settings
from sci_data_logger.vlm import QwenVLMClient
from sci_data_logger.vlm.client import (
    VLMGlobalConcurrencyTimeout,
    _reset_global_semaphore,
)


@pytest.fixture(autouse=True)
def _isolate_semaphore():
    """Each test starts and ends with a fresh semaphore."""
    _reset_global_semaphore()
    yield
    _reset_global_semaphore()


def _build_client(*, global_cap: int, acquire_timeout: float = 5.0) -> QwenVLMClient:
    return QwenVLMClient(
        settings=Settings(
            _env_file=None,
            DASHSCOPE_API_KEY="sk-test-noop",
            SCI_DATA_LOGGER_VLM_GLOBAL_CONCURRENCY=global_cap,
            SCI_DATA_LOGGER_VLM_GLOBAL_ACQUIRE_TIMEOUT=acquire_timeout,
            QWEN_MAX_RETRIES=1,
            QWEN_RETRY_BASE_DELAY=0.01,
            QWEN_RETRY_MAX_DELAY=0.02,
        )
    )


class _StubChoice:
    class message:  # noqa: N801 — matches openai shape
        content = "{}"


class _StubResponse:
    choices = [_StubChoice()]
    model = "stub"
    usage = None


def test_global_semaphore_caps_in_flight_calls(monkeypatch):
    """Spawn 8 threads against a cap of 2; verify peak in-flight == 2."""
    client = _build_client(global_cap=2, acquire_timeout=10.0)

    in_flight = 0
    peak = 0
    metric_lock = threading.Lock()
    barrier_released = threading.Event()

    def fake_create_completion(self, oai_client, image_url, prompt):
        nonlocal in_flight, peak
        with metric_lock:
            in_flight += 1
            if in_flight > peak:
                peak = in_flight
        # Hold the call long enough that the test would observe >2 if the
        # semaphore were broken.
        barrier_released.wait(timeout=2.0)
        with metric_lock:
            in_flight -= 1
        return _StubResponse()

    monkeypatch.setattr(QwenVLMClient, "_create_completion", fake_create_completion)
    monkeypatch.setattr(
        QwenVLMClient,
        "_image_data_url",
        staticmethod(lambda *a, **k: "data:image/jpeg;base64,Zg=="),
    )

    threads = [
        threading.Thread(target=client.analyze_image, args=("/tmp/fake.jpg", "p"))
        for _ in range(8)
    ]
    for t in threads:
        t.start()

    # Wait long enough that, if the semaphore were broken, peak would have
    # exceeded the cap.
    time.sleep(0.3)
    barrier_released.set()

    for t in threads:
        t.join(timeout=5.0)
        assert not t.is_alive(), "thread did not finish"

    assert peak == 2, f"expected peak in-flight == 2 (the cap), saw {peak}"


def test_global_semaphore_timeout_raises(monkeypatch):
    """Cap of 1 + a slow holder + a very short acquire_timeout → second call
    raises VLMGlobalConcurrencyTimeout instead of hanging forever."""
    client = _build_client(global_cap=1, acquire_timeout=0.1)

    holder_release = threading.Event()

    def slow_create(self, oai_client, image_url, prompt):
        holder_release.wait(timeout=2.0)
        return _StubResponse()

    monkeypatch.setattr(QwenVLMClient, "_create_completion", slow_create)
    monkeypatch.setattr(
        QwenVLMClient,
        "_image_data_url",
        staticmethod(lambda *a, **k: "data:image/jpeg;base64,Zg=="),
    )

    holder = threading.Thread(target=client.analyze_image, args=("/tmp/a.jpg", "p"))
    holder.start()
    time.sleep(0.05)  # let holder acquire the only slot

    with pytest.raises(VLMGlobalConcurrencyTimeout):
        client.analyze_image("/tmp/b.jpg", "p")

    holder_release.set()
    holder.join(timeout=2.0)


def test_global_semaphore_releases_on_inner_exception(monkeypatch):
    """If the underlying API call raises, the semaphore MUST be released —
    otherwise repeated failures exhaust the cap permanently."""
    client = _build_client(global_cap=1, acquire_timeout=1.0)

    def raising(self, oai_client, image_url, prompt):
        raise RuntimeError("simulated openai failure")

    monkeypatch.setattr(QwenVLMClient, "_create_completion", raising)
    monkeypatch.setattr(
        QwenVLMClient,
        "_image_data_url",
        staticmethod(lambda *a, **k: "data:image/jpeg;base64,Zg=="),
    )

    for _ in range(3):
        with pytest.raises(RuntimeError):
            client.analyze_image("/tmp/x.jpg", "p")
    # If the semaphore weren't released on exception, the 4th call would
    # hang for the full acquire_timeout. The fact that we get here means
    # the previous loop iterations all succeeded in re-acquiring.
