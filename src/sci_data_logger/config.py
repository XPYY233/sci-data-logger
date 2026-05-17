from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings loaded from environment variables and optional .env file."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    app_name: str = "Sci Data Logger"
    app_version: str = "0.1.0"

    dashscope_api_key: str | None = Field(default=None, alias="DASHSCOPE_API_KEY")
    qwen_base_url: str = Field(
        default="https://dashscope.aliyuncs.com/compatible-mode/v1",
        alias="QWEN_BASE_URL",
    )
    qwen_vlm_model: str = Field(default="qwen3.6-plus", alias="QWEN_VLM_MODEL")
    qwen_request_timeout: int = Field(default=180, alias="QWEN_REQUEST_TIMEOUT")
    qwen_vl_high_resolution_images: bool = Field(
        default=True,
        alias="QWEN_VL_HIGH_RESOLUTION_IMAGES",
    )
    qwen_image_max_side: int = Field(default=1600, alias="QWEN_IMAGE_MAX_SIDE")
    qwen_image_downscale_threshold_bytes: int = Field(
        default=1_500_000,
        alias="QWEN_IMAGE_DOWNSCALE_THRESHOLD_BYTES",
    )
    qwen_max_retries: int = Field(default=3, alias="QWEN_MAX_RETRIES")
    qwen_retry_base_delay: float = Field(default=1.0, alias="QWEN_RETRY_BASE_DELAY")
    qwen_retry_max_delay: float = Field(default=20.0, alias="QWEN_RETRY_MAX_DELAY")
    vlm_concurrency: int = Field(
        default=4,
        alias="SCI_DATA_LOGGER_VLM_CONCURRENCY",
    )

    storage_root: Path = Field(
        default=Path(".local_data"),
        alias="SCI_DATA_LOGGER_STORAGE_ROOT",
    )
    instrument_registry: Path = Field(
        default=Path("configs/instruments.example.json"),
        alias="SCI_DATA_LOGGER_INSTRUMENT_REGISTRY",
    )
    group_template: Path = Field(
        default=Path("configs/group_templates.example.json"),
        alias="SCI_DATA_LOGGER_GROUP_TEMPLATE",
    )

    image_autocontrast: bool = Field(
        default=True,
        alias="SCI_DATA_LOGGER_IMAGE_AUTOCONTRAST",
    )
    image_deskew: bool = Field(
        default=True,
        alias="SCI_DATA_LOGGER_IMAGE_DESKEW",
    )
    pdf_render_dpi: int = Field(
        default=200,
        alias="SCI_DATA_LOGGER_PDF_RENDER_DPI",
    )
    context_hint_enabled: bool = Field(
        default=False,
        alias="SCI_DATA_LOGGER_CONTEXT_HINT_ENABLED",
    )
    context_hint_tail_chars: int = Field(
        default=400,
        alias="SCI_DATA_LOGGER_CONTEXT_HINT_TAIL_CHARS",
    )

    def ensure_storage(self) -> Path:
        self.storage_root.mkdir(parents=True, exist_ok=True)
        return self.storage_root


@lru_cache
def get_settings() -> Settings:
    return Settings()
