"""Verify SCI_DATA_LOGGER_DB_STRIP_RAW_MODEL_OUTPUT actually shrinks rows
and that the structured catalog/event fields survive the strip.

Stripping `raw_model_output` is the deliberate tradeoff: typical VLM responses
are 50-500 KB per page, so a 50-page notebook can carry tens of MB of raw
payload that's only useful for debugging the prompt parser. The catalogs/events
that the orchestrator extracts upfront are first-class fields on the top-level
record and survive the strip.
"""
from __future__ import annotations

import pytest

from sci_data_logger.db import repository
from sci_data_logger.db.session import (
    get_engine,
    get_session_factory,
    init_db,
    reset_engine_cache,
)
from sci_data_logger.schemas import (
    ExperimentEvent,
    ExperimentRecord,
    Material,
    PagePacket,
    Sample,
)


@pytest.fixture
def db_session(monkeypatch, tmp_path):
    monkeypatch.setenv("SCI_DATA_LOGGER_STORAGE_ROOT", str(tmp_path))
    from sci_data_logger.config import get_settings

    get_settings.cache_clear()
    reset_engine_cache()
    engine = get_engine(get_settings())
    init_db(engine)
    factory = get_session_factory(engine)
    with factory() as session:
        yield session
    reset_engine_cache()
    get_settings.cache_clear()


def _make_record_with_fat_raw_output() -> ExperimentRecord:
    """Build a record whose page carries a non-trivial raw_model_output payload
    AND a populated materials_catalog at the top level (so we can verify the
    catalog survives strip).
    """
    fat_payload = {
        "json": {
            "materials": [{"name": "Mn2O3"} for _ in range(50)],
            "raw_text": "X" * 10_000,  # noisy, irrelevant verbatim text
        }
    }
    page = PagePacket(
        source_path="p.jpg",
        text_blocks=["lab note 1"],
        raw_model_output=fat_payload,
    )
    return ExperimentRecord(
        experiment_id="EXP-RAW",
        materials_catalog=[Material(canonical_name="Mn2O3", roles=["precursor"])],
        samples_catalog=[Sample(canonical_label="S1")],
        events=[
            ExperimentEvent(
                sequence_index=1,
                action_type="weigh",
                description="weigh 1.0 g",
                page_ref=page.page_id,
            )
        ],
        pages=[page],
    )


def test_strip_flag_off_persists_raw_model_output(monkeypatch, db_session):
    monkeypatch.delenv("SCI_DATA_LOGGER_DB_STRIP_RAW_MODEL_OUTPUT", raising=False)
    from sci_data_logger.config import get_settings

    get_settings.cache_clear()

    record = _make_record_with_fat_raw_output()
    repository.save_record(db_session, record)
    db_session.commit()

    loaded = repository.get_record(db_session, "EXP-RAW")
    assert loaded is not None
    # raw_model_output round-tripped intact
    assert loaded.pages[0].raw_model_output.get("json", {}).get("raw_text") == "X" * 10_000


def test_strip_flag_on_drops_raw_model_output_but_keeps_catalogs(
    monkeypatch, db_session
):
    monkeypatch.setenv("SCI_DATA_LOGGER_DB_STRIP_RAW_MODEL_OUTPUT", "true")
    from sci_data_logger.config import get_settings

    get_settings.cache_clear()

    record = _make_record_with_fat_raw_output()
    repository.save_record(db_session, record)
    db_session.commit()

    loaded = repository.get_record(db_session, "EXP-RAW")
    assert loaded is not None
    # raw_model_output is wiped to its default
    assert loaded.pages[0].raw_model_output == {}
    # But all the structured stuff orchestrator extracted is intact
    assert len(loaded.materials_catalog) == 1
    assert loaded.materials_catalog[0].canonical_name == "Mn2O3"
    assert len(loaded.samples_catalog) == 1
    assert len(loaded.events) == 1
    assert loaded.events[0].action_type == "weigh"
    # Other page-level fields survive too
    assert loaded.pages[0].text_blocks == ["lab note 1"]


def test_strip_flag_shrinks_row_size(monkeypatch, db_session):
    """Quantitative check: with strip ON, the stored record_json should be
    materially smaller than with strip OFF on the same input."""
    record = _make_record_with_fat_raw_output()

    monkeypatch.delenv("SCI_DATA_LOGGER_DB_STRIP_RAW_MODEL_OUTPUT", raising=False)
    from sci_data_logger.config import get_settings

    get_settings.cache_clear()
    fat_payload = repository._dump_record_for_db(record)

    monkeypatch.setenv("SCI_DATA_LOGGER_DB_STRIP_RAW_MODEL_OUTPUT", "true")
    get_settings.cache_clear()
    slim_payload = repository._dump_record_for_db(record)

    # The "fat" version has the 10k raw_text + 50 material dicts in the raw
    # payload; the slim version drops all of it. Conservatively assert at
    # least 5x shrink.
    assert len(slim_payload) * 5 < len(fat_payload), (
        f"slim={len(slim_payload)} vs fat={len(fat_payload)} — strip didn't help"
    )
