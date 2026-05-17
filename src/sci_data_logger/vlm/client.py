from __future__ import annotations

import base64
import logging
import mimetypes
import threading
from pathlib import Path
from typing import Any

import openai
from tenacity import (
    Retrying,
    retry_if_exception_type,
    stop_after_attempt,
    stop_after_delay,
    wait_random_exponential,
)

from sci_data_logger.config import Settings, get_settings
from sci_data_logger.errors import (
    VLMAuthenticationError,
    VLMBadRequestError,
    VLMGlobalConcurrencyTimeout,
    VLMNotConfiguredError,
    VLMTransientError,
)
from sci_data_logger.utils.json_tools import parse_first_json_object

logger = logging.getLogger(__name__)

# Transient errors worth retrying. BadRequestError / AuthenticationError are
# config bugs — retrying them just wastes quota.
_RETRYABLE_EXC: tuple[type[BaseException], ...] = (
    openai.RateLimitError,
    openai.APITimeoutError,
    openai.APIConnectionError,
    openai.InternalServerError,
)


# Process-wide semaphore around the actual VLM HTTP call. Sized at module
# import via the current Settings.vlm_global_concurrency; tests that change
# the env var must call `_reset_global_semaphore()` to rebuild it. The
# orchestrator's per-request ThreadPoolExecutor uses `vlm_concurrency`
# workers each; multiplied across many FastAPI request threads they can
# blow past DashScope quotas, so we gate at this single chokepoint.
_global_semaphore: threading.BoundedSemaphore | None = None
_global_semaphore_lock = threading.Lock()


def _get_global_semaphore(settings: Settings) -> threading.BoundedSemaphore:
    global _global_semaphore
    if _global_semaphore is None:
        with _global_semaphore_lock:
            if _global_semaphore is None:
                _global_semaphore = threading.BoundedSemaphore(
                    max(1, int(settings.vlm_global_concurrency))
                )
    return _global_semaphore


def _reset_global_semaphore() -> None:
    """Test helper: drop the cached semaphore so the next call re-reads
    Settings.vlm_global_concurrency. Production code should not call this."""
    global _global_semaphore
    with _global_semaphore_lock:
        _global_semaphore = None


# VLMGlobalConcurrencyTimeout was previously defined here as a RuntimeError
# subclass; it now lives in `sci_data_logger.errors` so the FastAPI global
# exception handler can map it to 503 alongside the other VLM exceptions.
# We re-export it for backward compat with any caller that imports from this
# module directly.
__all__ = ["QwenVLMClient", "VLMGlobalConcurrencyTimeout"]


class QwenVLMClient:
    """Small wrapper around the Qwen OpenAI-compatible vision chat API."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    @property
    def is_configured(self) -> bool:
        return bool(self.settings.dashscope_api_key)

    def analyze_image(self, image_path: Path, prompt: str) -> dict[str, Any]:
        if not self.settings.dashscope_api_key:
            raise VLMNotConfiguredError(
                "DASHSCOPE_API_KEY is not configured."
            )

        from openai import OpenAI

        # Acquire the process-wide chokepoint BEFORE building the OpenAI
        # client / encoding the image so we don't waste CPU on requests that
        # are about to be blocked. Timeout converts overload into a clean
        # 5xx-equivalent for the caller rather than an indefinite hang.
        sem = _get_global_semaphore(self.settings)
        timeout = float(self.settings.vlm_global_acquire_timeout)
        if not sem.acquire(timeout=timeout if timeout > 0 else None):
            raise VLMGlobalConcurrencyTimeout(
                f"Could not acquire VLM global semaphore within {timeout}s "
                f"(cap = {self.settings.vlm_global_concurrency}); "
                "lower request rate or raise SCI_DATA_LOGGER_VLM_GLOBAL_CONCURRENCY."
            )
        try:
            client = OpenAI(
                api_key=self.settings.dashscope_api_key,
                base_url=self.settings.qwen_base_url,
                timeout=self.settings.qwen_request_timeout,
            )
            image_url = self._image_data_url(
                image_path,
                max_side=self.settings.qwen_image_max_side,
                size_threshold=self.settings.qwen_image_downscale_threshold_bytes,
            )
            try:
                response = self._create_completion(client, image_url, prompt)
            # Translate openai library exceptions into our domain hierarchy
            # so route handlers don't deal with library types and clients get
            # stable HTTP statuses via the global exception handler.
            # Order matters: AuthenticationError is a BadRequestError subclass
            # in some openai SDK versions, so catch it first.
            except openai.AuthenticationError as exc:
                raise VLMAuthenticationError(
                    "DashScope rejected the API key. Fix DASHSCOPE_API_KEY."
                ) from exc
            except openai.BadRequestError as exc:
                raise VLMBadRequestError(
                    f"DashScope rejected the request "
                    f"(model={self.settings.qwen_vlm_model!r}): {exc}"
                ) from exc
            except _RETRYABLE_EXC as exc:
                # tenacity has already burned the retry budget — surface as
                # a transient error so the client knows a later retry MAY work.
                raise VLMTransientError(
                    f"Upstream VLM transient error after retries "
                    f"({type(exc).__name__}): {exc}"
                ) from exc
        finally:
            sem.release()

        content = response.choices[0].message.content or ""
        return {
            "raw_text": content,
            "json": parse_first_json_object(content),
            "model": response.model,
            "usage": response.usage.model_dump() if response.usage else None,
        }

    def _create_completion(self, client: Any, image_url: str, prompt: str) -> Any:
        """Call chat.completions.create with tenacity-driven retries.

        Uses imperative ``Retrying`` so retry budget/delays are read from
        ``self.settings`` at call time — tests construct clients with custom
        Settings, so decorator-time evaluation would freeze the wrong values.
        """
        max_retries = max(1, int(self.settings.qwen_max_retries))
        max_total_seconds = float(self.settings.qwen_retry_max_total_seconds)
        retryer = Retrying(
            stop=stop_after_attempt(max_retries) | stop_after_delay(max_total_seconds),
            wait=wait_random_exponential(
                multiplier=self.settings.qwen_retry_base_delay,
                max=self.settings.qwen_retry_max_delay,
            ),
            retry=retry_if_exception_type(_RETRYABLE_EXC),
            reraise=True,
        )
        for attempt in retryer:
            with attempt:
                attempt_num = attempt.retry_state.attempt_number
                if attempt_num > 1:
                    last_exc = attempt.retry_state.outcome.exception() if attempt.retry_state.outcome else None
                    logger.warning(
                        "VLM call retry %d/%d after %s: %s",
                        attempt_num,
                        max_retries,
                        type(last_exc).__name__ if last_exc else "unknown",
                        last_exc,
                    )
                return client.chat.completions.create(
                    model=self.settings.qwen_vlm_model,
                    messages=[
                        {
                            "role": "user",
                            "content": [
                                {
                                    "type": "image_url",
                                    "image_url": {"url": image_url},
                                },
                                {"type": "text", "text": prompt},
                            ],
                        }
                    ],
                    temperature=0,
                    extra_body={
                        "vl_high_resolution_images": self.settings.qwen_vl_high_resolution_images
                    },
                )
        # Unreachable: Retrying with reraise=True either returns or raises.
        raise RuntimeError("VLM retry loop exited without result")

    @staticmethod
    def _image_data_url(
        image_path: Path,
        max_side: int = 1600,
        size_threshold: int = 1_500_000,
    ) -> str:
        mime_type = mimetypes.guess_type(image_path.name)[0] or "image/jpeg"
        raw = image_path.read_bytes()
        if len(raw) > size_threshold:
            try:
                from PIL import Image
                import io

                with Image.open(image_path) as im:
                    im = im.convert("RGB")
                    w, h = im.size
                    long_side = max(w, h)
                    if long_side > max_side:
                        scale = max_side / long_side
                        im = im.resize((int(w * scale), int(h * scale)), Image.LANCZOS)
                    buf = io.BytesIO()
                    im.save(buf, format="JPEG", quality=88, optimize=True)
                    raw = buf.getvalue()
                    mime_type = "image/jpeg"
            except ImportError:
                pass
        data = base64.b64encode(raw).decode("ascii")
        return f"data:{mime_type};base64,{data}"
