"""Domain exception hierarchy for sci_data_logger.

All exceptions raised by application code (not by stdlib / third-party libs)
should inherit from ``SciDataLoggerError``. The FastAPI app installs a single
exception handler that maps the class -> HTTP status + structured JSON body,
so route handlers don't need scattered try/except plumbing for every kind of
upstream failure.

The handler emits this shape:

    {"error": {"type": "<ClassName>", "detail": "...", "retryable": <bool>}}

with status taken from ``http_status`` and a ``Retry-After: 60`` header when
``retryable`` is true. FastAPI's built-in ``HTTPException`` still uses its own
flat ``{"detail": "..."}`` shape — the two coexist on purpose: HTTPException is
for HTTP-level concerns (404 lookup miss, 401 missing key), domain exceptions
are for application-level failures (upstream broke, data corrupted).
"""
from __future__ import annotations


class SciDataLoggerError(Exception):
    """Base class for all in-house exceptions.

    Subclasses MUST set ``http_status`` (int) and MAY set ``retryable`` (bool,
    default False). Both are class attributes — the handler reads them off the
    instance via attribute lookup so subclasses can override.
    """

    http_status: int = 500
    retryable: bool = False


# ---------- Configuration: server set up wrong -------------------------------

class ConfigurationError(SciDataLoggerError):
    """Server-side misconfiguration. Operator must fix before retry helps."""

    http_status = 503


class VLMNotConfiguredError(ConfigurationError):
    """Replaces the legacy ``RuntimeError("DASHSCOPE_API_KEY is not configured.")``
    so callers can distinguish missing-key from network problems."""


# ---------- Upstream: VLM dependency broke -----------------------------------

class UpstreamError(SciDataLoggerError):
    """External dependency (VLM, …) returned an error we can't recover from
    inside this request."""


class VLMAuthenticationError(UpstreamError):
    """DashScope rejected the API key. Not retryable — fix the key."""

    http_status = 502


class VLMBadRequestError(UpstreamError):
    """The model/prompt/image was rejected upstream as malformed. Not
    retryable from the same payload — usually means wrong model id, prompt
    exceeded context, or image format unsupported."""

    http_status = 502


class VLMTransientError(UpstreamError):
    """Retries (tenacity) exhausted but the underlying error was transient
    (RateLimitError / APITimeoutError / APIConnectionError / 5xx). Client may
    retry later — the response carries Retry-After."""

    http_status = 503
    retryable = True


class VLMGlobalConcurrencyTimeout(UpstreamError):
    """Couldn't acquire the process-wide VLM dispatch semaphore within
    ``vlm_global_acquire_timeout`` seconds. Means sustained over-saturation
    of the DashScope chokepoint — back off or raise the cap."""

    http_status = 503
    retryable = True


# ---------- Data: stored state corrupted -------------------------------------

class CorruptRecordError(SciDataLoggerError):
    """The DB row exists but its ``record_json`` blob can't be parsed back
    into ``ExperimentRecord``. Usually means schema migration drift or a
    direct DB edit; not safe to retry — manual fix required."""

    http_status = 500

    def __init__(self, experiment_id: str, *, cause: Exception | None = None) -> None:
        super().__init__(
            f"stored record {experiment_id!r} is corrupted "
            f"(JSON failed to validate against current ExperimentRecord schema)"
        )
        self.experiment_id = experiment_id
        if cause is not None:
            self.__cause__ = cause
