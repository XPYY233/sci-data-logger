from __future__ import annotations

import base64
from pathlib import Path

import pytest

from sci_data_logger.vlm.client import QwenVLMClient


def _make_large_jpeg(path: Path, side: int = 4000) -> int:
    """Write a JPEG that exceeds the downscale threshold; return its byte size."""
    pytest.importorskip("PIL")
    from PIL import Image

    img = Image.new("RGB", (side, side))
    # Sprinkle pseudo-random pixels so JPEG compression doesn't collapse to a few bytes
    rng = __import__("random").Random(42)
    pixels = img.load()
    for x in range(0, side, 16):
        for y in range(0, side, 16):
            pixels[x, y] = (rng.randrange(256), rng.randrange(256), rng.randrange(256))
    img.save(path, format="JPEG", quality=95)
    return path.stat().st_size


def test_image_data_url_downscales_large_image(tmp_path: Path) -> None:
    pytest.importorskip("PIL")
    image_path = tmp_path / "huge.jpg"
    original_size = _make_large_jpeg(image_path, side=4000)
    assert original_size > 1_500_000, (
        f"baseline image must exceed downscale threshold; got {original_size} bytes"
    )

    data_url = QwenVLMClient._image_data_url(image_path, max_side=1600, size_threshold=1_500_000)

    assert data_url.startswith("data:image/jpeg;base64,")
    encoded = data_url.split(",", 1)[1]
    new_size = len(base64.b64decode(encoded))
    assert new_size < original_size


def test_image_data_url_skips_downscale_when_pillow_missing(tmp_path: Path, monkeypatch) -> None:
    pytest.importorskip("PIL")
    image_path = tmp_path / "huge.jpg"
    original_size = _make_large_jpeg(image_path, side=4000)
    assert original_size > 1_500_000

    import builtins

    real_import = builtins.__import__

    def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "PIL" or name.startswith("PIL."):
            raise ImportError("PIL unavailable for test")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    data_url = QwenVLMClient._image_data_url(image_path, max_side=1600, size_threshold=1_500_000)
    encoded = data_url.split(",", 1)[1]
    new_size = len(base64.b64decode(encoded))
    # fallback returned the raw bytes
    assert new_size == original_size
