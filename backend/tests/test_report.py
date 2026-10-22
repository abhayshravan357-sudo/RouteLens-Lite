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


class TestReportHonesty:
    """
    The report must not promise more than it delivers.

    These cover the two ways the export used to mislead: it called the
    teaching table the only simulated thing, and it showed only half of
    the machine's routing tables.
    """

    @pytest.mark.asyncio
    async def test_the_limitations_name_every_modelled_part(self):
        """
        The limitations say which parts are modelled.

        There are two modelled sections, not one, and a reader must be able
        to tell from the limitations alone.
        """
        report = await build_report()
        modelled = {
            section.title
            for section in report.sections
            if any(item.provenance == "simulated" for item in section.evidence)
        }
        assert len(modelled) >= 2, f"expected more than one modelled section, got {modelled}"

        first = LIMITATIONS[0].lower()
        for word in ("teaching", "scenario"):
            assert word in first, (
                f"the first limitation does not mention the {word} part, so a "
                "reader cannot tell what is modelled"
            )
        # It must not claim that only one thing is simulated.
        assert not first.startswith("only "), (
            "the first limitation says 'only', but more than one part is modelled"
        )

    @pytest.mark.asyncio
    async def test_the_ipv6_table_is_in_the_report(self):
        """The kernel keeps two tables; the report must not show only one."""
        report = await build_report()
        machine = next(s for s in report.sections if s.title == "This machine")

        families = {item.family for item in machine.evidence if item.family}
        assert "ipv4" in families, "the report has no IPv4 evidence"
        assert "ipv6" in families, (
            "the report has no IPv6 evidence, so a reader would conclude the "
            "machine has no IPv6 routes"
        )

    @pytest.mark.asyncio
    async def test_the_evidence_says_which_family_it_came_from(self):
        """Each network evidence item names the family it was read from."""
        report = await build_report()
        machine = next(s for s in report.sections if s.title == "This machine")

        routes = [i for i in machine.evidence if i.label.startswith("Route ")]
        assert routes, "the report has no route evidence"
        for item in routes:
            assert item.family in ("ipv4", "ipv6"), (
                f"{item.label} does not say which family it came from"
            )

    @pytest.mark.asyncio
    async def test_an_empty_table_is_not_reported_as_unreadable(self):
        """
        A table that was read and is empty is not a table that failed.

        This machine has an empty IPv6 neighbour cache. Saying "not
        collected" would tell a reader the collection failed.
        """
        report = await build_report()
        machine = next(s for s in report.sections if s.title == "This machine")

        for item in machine.evidence:
            if item.label.startswith("Neighbours (") or item.label.startswith(
                "Routing table ("
            ):
                assert item.provenance != "unknown" or "not collected" not in str(
                    item.value
                ), (
                    f"{item.label} says it was not collected, but it was "
                    f"read and was empty: {item.value!r}"
                )

    @pytest.mark.asyncio
    async def test_the_neighbour_names_are_kept(self):
        """
        A neighbour's resolved name is evidence and must not be discarded.

        The collector looks the name up, so throwing it away wastes a DNS
        query and loses information the reader can use.
        """
        report = await build_report()
        machine = next(s for s in report.sections if s.title == "This machine")

        neighbours = [i for i in machine.evidence if i.label.startswith("Neighbour ")]
        assert neighbours, "the report has no neighbour evidence"
        for item in neighbours:
            assert isinstance(item.value, dict), "the neighbour evidence is not a mapping"
            assert "hostname" in item.value, (
                f"{item.label} does not carry the name that was looked up"
            )
            assert "name_provenance" in item.value, (
                f"{item.label} does not say where its name came from"
            )
