from sci_data_logger.utils.date_heuristics import label_to_iso


def test_label_to_iso_basic_month_day():
    assert label_to_iso("5.20", default_year=2026) == "2026-05-20"
    assert label_to_iso("6.10", default_year=2026) == "2026-06-10"
    assert label_to_iso("12.31", default_year=2026) == "2026-12-31"


def test_label_to_iso_full_date():
    assert label_to_iso("2026-05-20") == "2026-05-20"
    assert label_to_iso("2026.5.20", default_year=2026) == "2026-05-20"


def test_label_to_iso_unparseable_returns_none():
    assert label_to_iso("Day 3") is None
    assert label_to_iso(None) is None
    assert label_to_iso("") is None
    assert label_to_iso("???") is None
