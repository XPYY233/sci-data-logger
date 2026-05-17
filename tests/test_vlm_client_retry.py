from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import openai
import pytest

from sci_data_logger.config import Settings
from sci_data_logger.vlm.client import QwenVLMClient


# --- Helpers ----------------------------------------------------------------
# Constructing openai's exceptions normally requires a body+response. Subclass
# with a no-arg __init__ so tenacity's isinstance() predicate still fires while
# sidestepping the SDK's awkward constructor signature.
class _FakeRateLimit(openai.RateLimitError):
    def __init__(self) -> None:  # noqa: D401 - test stub
        Exception.__init__(self, "rate limited (test)")


class _FakeTimeout(openai.APITimeoutError):
    def __init__(self) -> None:
        Exception.__init__(self, "timeout (test)")


class _FakeBadRequest(openai.BadRequestError):
    def __init__(self) -> None:
        Exception.__init__(self, "bad request (test)")


class _FakeUsage:
    def model_dump(self) -> dict[str, Any]:
        return {"prompt_tokens": 1, "completion_tokens": 1}


class _FakeMessage:
    def __init__(self, content: str) -> None:
        self.content = content


class _FakeChoice:
    def __init__(self, content: str) -> None:
        self.message = _FakeMessage(content)


class _FakeResponse:
    def __init__(self, content: str = '{"ok": true}') -> None:
        self.choices = [_FakeChoice(content)]
        self.model = "qwen-test"
        self.usage = _FakeUsage()


class _ScriptedCompletions:
    """Drop-in for ``client.chat.completions`` with a scripted error sequence."""

    def __init__(self, script: list[Any]) -> None:
        # Each entry is either an Exception (instance) to raise, or a value to return.
        self._script = list(script)
        self.calls = 0

    def create(self, **_kwargs: Any) -> Any:
        self.calls += 1
        if not self._script:
            raise AssertionError("scripted completions exhausted")
        nxt = self._script.pop(0)
        if isinstance(nxt, BaseException):
            raise nxt
        return nxt


class _FakeChat:
    def __init__(self, completions: _ScriptedCompletions) -> None:
        self.completions = completions


class _FakeOpenAIClient:
    def __init__(self, script: list[Any]) -> None:
        self.chat = _FakeChat(_ScriptedCompletions(script))

    @property
    def calls(self) -> int:
        return self.chat.completions.calls


def _fast_settings() -> Settings:
    return Settings(
        DASHSCOPE_API_KEY="sk-test",
        QWEN_MAX_RETRIES=3,
        QWEN_RETRY_BASE_DELAY=0.01,
        QWEN_RETRY_MAX_DELAY=0.02,
    )


def _patch_openai(monkeypatch: pytest.MonkeyPatch, fake: _FakeOpenAIClient) -> None:
    """Replace ``openai.OpenAI`` so analyze_image gets our fake client."""
    def _factory(*_args: Any, **_kwargs: Any) -> _FakeOpenAIClient:
        return fake

    import openai as openai_mod

    monkeypatch.setattr(openai_mod, "OpenAI", _factory)


def _stub_image_data_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        QwenVLMClient,
        "_image_data_url",
        staticmethod(lambda *a, **k: "data:image/jpeg;base64,AAAA"),
    )


# --- Tests ------------------------------------------------------------------
def test_vlm_retries_on_rate_limit_then_succeeds(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    fake = _FakeOpenAIClient(
        [_FakeRateLimit(), _FakeRateLimit(), _FakeResponse('{"answer": 42}')]
    )
    _patch_openai(monkeypatch, fake)
    _stub_image_data_url(monkeypatch)

    client = QwenVLMClient(settings=_fast_settings())
    image_path = tmp_path / "stub.jpg"
    image_path.write_bytes(b"\xff\xd8\xff\xd9")  # minimal JPEG sentinel; downscale path stubbed

    result = client.analyze_image(image_path, "hi")

    assert fake.calls == 3
    assert result["model"] == "qwen-test"
    assert result["json"] == {"answer": 42}


def test_vlm_does_not_retry_on_bad_request(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    fake = _FakeOpenAIClient([_FakeBadRequest()])
    _patch_openai(monkeypatch, fake)
    _stub_image_data_url(monkeypatch)

    client = QwenVLMClient(settings=_fast_settings())
    image_path = tmp_path / "stub.jpg"
    image_path.write_bytes(b"\xff\xd8\xff\xd9")

    with pytest.raises(openai.BadRequestError):
        client.analyze_image(image_path, "hi")

    assert fake.calls == 1


def test_vlm_gives_up_after_max_retries(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    fake = _FakeOpenAIClient([_FakeTimeout(), _FakeTimeout(), _FakeTimeout()])
    _patch_openai(monkeypatch, fake)
    _stub_image_data_url(monkeypatch)

    settings = _fast_settings()
    client = QwenVLMClient(settings=settings)
    image_path = tmp_path / "stub.jpg"
    image_path.write_bytes(b"\xff\xd8\xff\xd9")

    with pytest.raises(openai.APITimeoutError):
        client.analyze_image(image_path, "hi")

    assert fake.calls == settings.qwen_max_retries == 3


def test_vlm_retry_gives_up_at_total_wallclock_cap(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A huge ``qwen_max_retries`` must still be bounded by the wallclock cap.

    Under sustained 429/timeout storms, ``stop_after_attempt`` alone leaves a
    single VLM call sleeping for minutes (max_retries × max_delay). We combine
    it with ``stop_after_delay`` so the whole retry loop has a hard ceiling.
    """
    # 50 scripted timeouts is more than the cap can possibly burn through.
    fake = _FakeOpenAIClient([_FakeTimeout() for _ in range(50)])
    _patch_openai(monkeypatch, fake)
    _stub_image_data_url(monkeypatch)

    settings = Settings(
        DASHSCOPE_API_KEY="sk-test",
        QWEN_MAX_RETRIES=100,
        QWEN_RETRY_BASE_DELAY=0.05,
        QWEN_RETRY_MAX_DELAY=0.1,
        QWEN_RETRY_MAX_TOTAL_SECONDS=0.3,
    )
    client = QwenVLMClient(settings=settings)
    image_path = tmp_path / "stub.jpg"
    image_path.write_bytes(b"\xff\xd8\xff\xd9")

    start = time.monotonic()
    with pytest.raises(openai.APITimeoutError):
        client.analyze_image(image_path, "hi")
    elapsed = time.monotonic() - start

    # Hard ceiling: total time well under what max_retries=100 × 0.1s would burn.
    # Generous slack accounts for retry bookkeeping overhead.
    assert elapsed < 2.0, f"retry loop exceeded wallclock cap: {elapsed:.2f}s"
    # And we definitely did not run all 100 attempts.
    assert fake.calls < 50
