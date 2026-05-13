from __future__ import annotations

import base64
import mimetypes
from pathlib import Path
from typing import Any

from sci_data_logger.config import Settings, get_settings
from sci_data_logger.utils.json_tools import parse_first_json_object


class QwenVLMClient:
    """Small wrapper around the Qwen OpenAI-compatible vision chat API."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    @property
    def is_configured(self) -> bool:
        return bool(self.settings.dashscope_api_key)

    def analyze_image(self, image_path: Path, prompt: str) -> dict[str, Any]:
        if not self.settings.dashscope_api_key:
            raise RuntimeError("DASHSCOPE_API_KEY is not configured.")

        from openai import OpenAI

        client = OpenAI(
            api_key=self.settings.dashscope_api_key,
            base_url=self.settings.qwen_base_url,
            timeout=self.settings.qwen_request_timeout,
        )
        response = client.chat.completions.create(
            model=self.settings.qwen_vlm_model,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": self._image_data_url(
                                    image_path,
                                    max_side=self.settings.qwen_image_max_side,
                                    size_threshold=self.settings.qwen_image_downscale_threshold_bytes,
                                )
                            },
                        },
                        {"type": "text", "text": prompt},
                    ],
                }
            ],
            temperature=0,
            extra_body={"vl_high_resolution_images": self.settings.qwen_vl_high_resolution_images},
        )
        content = response.choices[0].message.content or ""
        return {
            "raw_text": content,
            "json": parse_first_json_object(content),
            "model": response.model,
            "usage": response.usage.model_dump() if response.usage else None,
        }

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
