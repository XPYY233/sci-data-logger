from __future__ import annotations

from pathlib import Path

import pytest


def test_read_capture_time_returns_iso_string(tmp_path: Path) -> None:
    """Build a tiny JPEG with a DateTimeOriginal EXIF tag and verify the parser
    returns an ISO 8601 string. Falls back to mocking PIL.Image.open if writing
    EXIF round-trip is unavailable in this environment.
    """
    PIL = pytest.importorskip("PIL")
    from PIL import ExifTags, Image

    from sci_data_logger.services.document import _read_capture_time

    jpg_path = tmp_path / "with_exif.jpg"

    # Try real EXIF round-trip via Pillow's Exif object.
    wrote_real_exif = False
    try:
        img = Image.new("RGB", (8, 8), color="white")
        exif = img.getexif()
        # Find the numeric tag id for DateTimeOriginal
        tag_map = {v: k for k, v in ExifTags.TAGS.items()}
        dto_tag = tag_map.get("DateTimeOriginal")
        dt_tag = tag_map.get("DateTime")
        if dto_tag is not None:
            exif[dto_tag] = "2026:05:14 09:23:41"
        if dt_tag is not None:
            exif[dt_tag] = "2026:05:14 09:23:41"
        img.save(jpg_path, format="JPEG", exif=exif.tobytes())
        # Sanity-check the file can be read back with EXIF.
        with Image.open(jpg_path) as probe:
            probe_exif = probe._getexif() or {}
        if probe_exif.get(dto_tag) or probe_exif.get(dt_tag):
            wrote_real_exif = True
    except Exception:
        wrote_real_exif = False

    if wrote_real_exif:
        result = _read_capture_time(jpg_path)
        assert result == "2026-05-14T09:23:41"
        return

    # Fallback: monkey-patch PIL.Image.open to return a fake image with EXIF.
    class _FakeExifImage:
        def __init__(self, exif_dict):
            self._exif = exif_dict

        def _getexif(self):
            return self._exif

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    tag_map = {v: k for k, v in ExifTags.TAGS.items()}
    fake_exif = {tag_map["DateTimeOriginal"]: "2026:05:14 09:23:41"}

    import PIL.Image as PILImage

    original_open = PILImage.open
    try:
        PILImage.open = lambda *_a, **_kw: _FakeExifImage(fake_exif)
        result = _read_capture_time(jpg_path)
    finally:
        PILImage.open = original_open

    assert result == "2026-05-14T09:23:41"
