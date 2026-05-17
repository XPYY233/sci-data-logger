"""Guardrail tests for PAGE_ANALYSIS_PROMPT content.

These tests lock in that the prompt asks the VLM for the new catalog + event
schema. Without these, a future edit could silently revert to the legacy
materials/steps/instruments-only form, breaking Gaps 4/5/6 in production
while leaving unit tests (which hand-craft PagePackets) green.
"""
from __future__ import annotations

from sci_data_logger.prompts import PAGE_ANALYSIS_PROMPT


def test_prompt_requests_materials_catalog():
    assert "materials_catalog" in PAGE_ANALYSIS_PROMPT
    assert "MaterialCatalogEntry" in PAGE_ANALYSIS_PROMPT
    assert "canonical_name" in PAGE_ANALYSIS_PROMPT
    assert "aliases" in PAGE_ANALYSIS_PROMPT


def test_prompt_requests_instruments_catalog():
    assert "instruments_catalog" in PAGE_ANALYSIS_PROMPT
    assert "InstrumentCatalogEntry" in PAGE_ANALYSIS_PROMPT
    assert "instrument_label" in PAGE_ANALYSIS_PROMPT


def test_prompt_requests_samples_catalog():
    assert "samples_catalog" in PAGE_ANALYSIS_PROMPT
    assert "SampleCatalogEntry" in PAGE_ANALYSIS_PROMPT
    assert "canonical_label" in PAGE_ANALYSIS_PROMPT


def test_prompt_requests_events_with_local_refs():
    assert "ExperimentEvent" in PAGE_ANALYSIS_PROMPT
    assert "material_ref_local" in PAGE_ANALYSIS_PROMPT
    assert "instrument_ref_local" in PAGE_ANALYSIS_PROMPT
    assert "sample_ref_local" in PAGE_ANALYSIS_PROMPT
    assert "action_type" in PAGE_ANALYSIS_PROMPT


def test_prompt_example_demonstrates_event_chain():
    """The example output should contain a multi-event scenario with at least
    one input referencing a material the catalog declares. This protects the
    "events also appear in the example" expectation."""
    # The example block lives near the bottom of the prompt.
    assert '"events"' in PAGE_ANALYSIS_PROMPT
    # And there should be at least one event input or output using a
    # material_ref_local.
    assert '"material_ref_local"' in PAGE_ANALYSIS_PROMPT
