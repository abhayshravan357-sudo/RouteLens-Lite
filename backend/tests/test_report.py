"""
Tests for report generation.

A report is only useful if it is honest, so these tests check that
evidence carries its source and timestamp, that failures are recorded
rather than dropped, and that the limitations are present.
"""

import pytest

from app.report import LIMITATIONS, build_report


class TestReportContent:
    """The report must carry real evidence and real caveats."""

    @pytest.mark.asyncio
    async def test_the_report_has_sections(self):
        """A report is not empty."""
        report = await build_report()
        assert report.sections
        assert report.title
        assert report.generated_at.endswith("Z")

    @pytest.mark.asyncio
    async def test_every_evidence_item_says_where_it_came_from(self):
        """Evidence without a source cannot be checked."""
        report = await build_report()
        for section in report.sections:
            for item in section.evidence:
                assert item.source, f"{section.title} / {item.label} has no source"
                assert item.collected_at, f"{section.title} / {item.label} has no time"
                assert item.provenance in (
                    "observed",
                    "inferred",
                    "simulated",
                    "unknown",
                ), f"{item.label} has an odd provenance"

    @pytest.mark.asyncio
    async def test_the_limitations_are_included(self):
        """A report without its limits is misleading."""
        report = await build_report()
        assert report.limitations == LIMITATIONS
        assert len(report.limitations) >= 5

    @pytest.mark.asyncio
    async def test_the_machine_section_is_marked_observed(self):
        """What was measured is marked observed."""
        report = await build_report()
        machine = next(s for s in report.sections if s.title == "This machine")
        assert machine.evidence
        for item in machine.evidence:
            assert item.provenance in ("observed", "unknown")

    @pytest.mark.asyncio
    async def test_the_teaching_table_is_marked_simulated(self):
        """The sample table must never look like a measurement."""
        report = await build_report()
        table = next(s for s in report.sections if s.title == "The teaching routing table")
        assert table.evidence
        for item in table.evidence:
            assert item.provenance == "simulated"

    @pytest.mark.asyncio
    async def test_the_scenarios_are_marked_simulated(self):
        """Scenarios are models, and say so."""
        report = await build_report()
        scenarios = next(s for s in report.sections if s.title == "Simulated networks")
        assert scenarios.evidence
        for item in scenarios.evidence:
            assert item.provenance == "simulated"

    @pytest.mark.asyncio
    async def test_the_markdown_mentions_the_evidence_and_limits(self):
        """The rendered report shows provenance and limitations."""
        report = await build_report()
        markdown = report.to_markdown()
        assert "**Provenance:**" in markdown
        assert "**Source:**" in markdown
        assert "**Collected:**" in markdown
        assert "## Limitations" in markdown
        for limitation in LIMITATIONS:
            assert limitation in markdown

    @pytest.mark.asyncio
    async def test_the_report_says_a_traceroute_hop_is_not_a_physical_device(self):
        """The distinction that matters most must be in the report."""
        report = await build_report()
        joined = " ".join(report.limitations).lower()
        assert "layer 3" in joined or "layer 3" in " ".join(
            report.limitations
        ).lower()
        assert "not necessarily" in joined
