from pathlib import Path

from sci_data_logger.services.instrument import InstrumentService


def test_instrument_profile_matches_example_xrd() -> None:
    service = InstrumentService()
    profile = service.match_profile(Path("sample_smartlab_xrd_report.txt"))
    assert profile is not None
    assert profile.technique == "XRD"
