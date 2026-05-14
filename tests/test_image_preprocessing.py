from __future__ import annotations

from PIL import Image, ImageDraw

from sci_data_logger.utils.image_preprocessing import (
    _best_skew_angle,
    preprocess_for_vlm,
)


def _low_contrast_image(width: int = 60, height: int = 40) -> Image.Image:
    """Build a small RGB image with values in [100, 120] (very low contrast)."""
    im = Image.new("RGB", (width, height))
    pixels = []
    for y in range(height):
        for x in range(width):
            v = 100 + ((x + y) % 21)  # 100..120
            pixels.append((v, v, v))
    im.putdata(pixels)
    return im


def test_preprocess_returns_rgb_image_with_autocontrast() -> None:
    src = _low_contrast_image()
    src_extrema = src.convert("L").getextrema()
    assert src_extrema[1] - src_extrema[0] <= 20

    # disable deskew to isolate autocontrast effect
    out = preprocess_for_vlm(src, autocontrast=True, deskew=False)
    assert out.mode == "RGB"
    out_extrema = out.convert("L").getextrema()
    assert (out_extrema[1] - out_extrema[0]) > (src_extrema[1] - src_extrema[0])


def _bar_image(angle_deg: float = 0.0) -> Image.Image:
    """White canvas with a thick black horizontal bar, optionally rotated."""
    im = Image.new("RGB", (240, 160), (255, 255, 255))
    draw = ImageDraw.Draw(im)
    # Multiple thin bars give the row-projection more structure than a single block.
    for y in (40, 70, 100, 130):
        draw.rectangle([20, y - 4, 220, y + 4], fill=(0, 0, 0))
    if angle_deg != 0.0:
        im = im.rotate(angle_deg, resample=Image.BICUBIC, expand=False, fillcolor=(255, 255, 255))
    return im


def test_preprocess_deskews_rotated_image() -> None:
    rotated = _bar_image(angle_deg=5.0)
    angle_before = _best_skew_angle(rotated)
    out = preprocess_for_vlm(rotated, autocontrast=False, deskew=True)
    angle_after = _best_skew_angle(out)
    assert abs(angle_after) < abs(angle_before)


def test_preprocess_no_op_when_both_flags_false() -> None:
    src = _low_contrast_image()
    out = preprocess_for_vlm(src, autocontrast=False, deskew=False)
    # Output is a new RGB conversion but pixel data identical
    assert list(out.getdata()) == list(src.convert("RGB").getdata())
