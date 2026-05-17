from __future__ import annotations

from pathlib import Path

from PIL import Image

from sci_data_logger.schemas import PagePacket
from sci_data_logger.services.document import DocumentProcessor
from sci_data_logger.utils.json_tools import parse_first_json_object


class FakeVLMClient:
    """Stub VLM returning a minimal valid JSON payload regardless of input."""

    def analyze_image(self, image_path: Path, prompt: str) -> dict[str, object]:
        return {
            "raw_text": "{}",
            "json": parse_first_json_object("{}") or {
                "page_types": ["synthesis_note"],
                "open_questions": [],
                "warnings": [],
                "review_required": False,
            },
            "model": "fake",
            "usage": None,
        }


def _make_two_page_pdf(path: Path) -> None:
    im1 = Image.new("RGB", (200, 280), (255, 255, 255))
    im2 = Image.new("RGB", (200, 280), (240, 240, 240))
    im1.save(path, save_all=True, append_images=[im2])


def test_analyze_pages_returns_one_packet_per_pdf_page(tmp_path: Path, monkeypatch) -> None:
    pdf_path = tmp_path / "notebook.pdf"
    _make_two_page_pdf(pdf_path)

    dp = DocumentProcessor(vlm_client=FakeVLMClient())

    captured_paths: list[Path] = []
    original = dp._analyze_image

    def stub_analyze_image(image_path: Path, prev_tail: str | None = None) -> PagePacket:
        captured_paths.append(image_path)
        # Return a minimal packet with the temp path as source — matches the real
        # implementation's behavior before _analyze_pdf rewrites source_path.
        return PagePacket(source_path=str(image_path))

    monkeypatch.setattr(dp, "_analyze_image", stub_analyze_image)

    packets = dp.analyze_pages(pdf_path)
    # Touch `original` so it isn't reported as unused by linters
    assert original is not stub_analyze_image

    assert len(packets) == 2
    assert packets[0].source_path == f"{pdf_path}#page=1"
    assert packets[1].source_path == f"{pdf_path}#page=2"
    # PDF evidence ref attached with pdf_page locator
    assert any(
        ref.locator.get("pdf_page") == 1 and ref.locator.get("path") == str(pdf_path)
        for ref in packets[0].evidence_refs
    )
    assert any(
        ref.locator.get("pdf_page") == 2 for ref in packets[1].evidence_refs
    )
    # Two distinct temp files were rendered and forwarded to the (stubbed) VLM
    assert len(captured_paths) == 2
    assert captured_paths[0] != captured_paths[1]


def test_analyze_pages_for_image_returns_singleton_list(tmp_path: Path) -> None:
    image_path = tmp_path / "page.jpg"
    Image.new("RGB", (40, 40), (255, 255, 255)).save(image_path, format="JPEG")

    dp = DocumentProcessor(vlm_client=FakeVLMClient())
    packets = dp.analyze_pages(image_path)
    assert len(packets) == 1
    assert packets[0].source_path == str(image_path)
