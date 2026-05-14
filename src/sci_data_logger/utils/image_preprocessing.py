"""Lightweight image preprocessing for handwritten notebook pages before VLM submission.

Pillow-only on purpose: no OpenCV / numpy hard requirement so deployment stays trivial.
The deskew heuristic is intentionally cheap — scan a coarse angle grid and pick the
one that maximizes the variance of the horizontal row-sum projection (text lines
produce a strongly peaked projection when rotated upright).
"""
from __future__ import annotations

from PIL import Image, ImageOps


_DESKEW_ANGLE_RANGE = 8.0  # degrees
_DESKEW_ANGLE_STEP = 0.5
_DESKEW_TRIGGER_THRESHOLD = 0.5  # only rotate if |best_angle| exceeds this
_PROJECTION_MAX_SIDE = 600  # downscale before computing projection to keep cost low


def _row_sum_variance(gray: Image.Image) -> float:
    """Variance of the per-row pixel-sum projection.

    Upright text → rows alternate (dark text rows, bright gaps) → high variance.
    Skewed text smears across rows → lower variance.
    """
    w, h = gray.size
    if w == 0 or h == 0:
        return 0.0
    # Pillow getdata returns a flat sequence in row-major order.
    pixels = list(gray.getdata())
    row_sums = [0] * h
    idx = 0
    for r in range(h):
        s = 0
        # invert so that "ink" is high-valued, gaps are low-valued
        for _ in range(w):
            s += 255 - pixels[idx]
            idx += 1
        row_sums[r] = s
    mean = sum(row_sums) / h
    return sum((x - mean) ** 2 for x in row_sums) / h


def _best_skew_angle(im_rgb: Image.Image) -> float:
    # Downscale for projection sampling — angle accuracy is unaffected at 600px.
    work = im_rgb.convert("L")
    w, h = work.size
    longest = max(w, h)
    if longest > _PROJECTION_MAX_SIDE:
        scale = _PROJECTION_MAX_SIDE / longest
        work = work.resize((max(1, int(w * scale)), max(1, int(h * scale))), Image.BILINEAR)

    best_angle = 0.0
    best_score = _row_sum_variance(work)
    angle = -_DESKEW_ANGLE_RANGE
    while angle <= _DESKEW_ANGLE_RANGE + 1e-9:
        if abs(angle) < 1e-9:
            angle += _DESKEW_ANGLE_STEP
            continue
        rotated = work.rotate(angle, resample=Image.BILINEAR, expand=False, fillcolor=255)
        score = _row_sum_variance(rotated)
        if score > best_score:
            best_score = score
            best_angle = angle
        angle += _DESKEW_ANGLE_STEP
    return best_angle


def preprocess_for_vlm(
    im: Image.Image,
    *,
    autocontrast: bool = True,
    deskew: bool = True,
) -> Image.Image:
    """Return a preprocessed RGB copy of *im* suitable for VLM ingestion."""
    out = im.convert("RGB")
    if autocontrast:
        out = ImageOps.autocontrast(out, cutoff=1)
    if deskew:
        angle = _best_skew_angle(out)
        if abs(angle) > _DESKEW_TRIGGER_THRESHOLD:
            out = out.rotate(
                angle,
                resample=Image.BICUBIC,
                expand=False,
                fillcolor=(255, 255, 255),
            )
    return out
