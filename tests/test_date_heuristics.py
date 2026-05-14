from sci_data_logger.utils.date_heuristics import infer_default_year, label_to_iso


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


def test_label_to_iso_md_without_default_year_returns_none():
    assert label_to_iso("5.20") is None
    assert label_to_iso("6.10", default_year=None) is None


def test_label_to_iso_md_with_explicit_default_year():
    assert label_to_iso("5.20", default_year=2024) == "2024-05-20"
    assert label_to_iso("5.20", default_year=2026) == "2026-05-20"


def test_infer_default_year_picks_from_ymd_label():
    assert infer_default_year(["5.20", "2024-09-18", "6.10"]) == 2024
    assert infer_default_year(["2024.9.18"]) == 2024
    assert infer_default_year(["5.20", "6.10"]) is None
    assert infer_default_year([]) is None
    assert infer_default_year([None, ""]) is None
