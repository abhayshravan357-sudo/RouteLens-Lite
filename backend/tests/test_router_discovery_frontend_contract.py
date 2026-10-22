"""
Tests for the wave-3 findings about the router discovery frontend.

The frontend is Agent C's file, so these tests are about the CONTRACT
between the frontend and the API, and they are written so that they fail
against a frontend that breaks the contract. They are not a fix.

The three rules being checked:

- A device that was NOT reached must not be presented as a device with
  nothing on it. A reader must not be told "this device reported no
  routes. That is a real reading" about a device that reported nothing.
- A finding that rests on an inference must say so IN THE FINDING, not in a
  separate field the reader has to know to look at.
- A run that stopped at a limit must say it stopped at a limit, so a small
  result is not mistaken for a complete one.
"""

import re
import subprocess
import sys
from pathlib import Path

import pytest


# --------------------------------------------------------------------------
# The frontend source is read, not imported: it is TypeScript, and it may
# not have landed in this branch.
# --------------------------------------------------------------------------

FRONTEND = Path(__file__).resolve().parents[2] / "frontend" / "src"


def _source(name: str) -> str:
    """The text of a frontend file, or a skip if it is not here."""
    path = FRONTEND / name
    if not path.exists():
        pytest.skip(f"{name} has not landed in this branch")
    return path.read_text()


def _branch_file(branch: str, name: str) -> str:
    """A file from a branch, or a skip if the branch is not available."""
    repo = Path(__file__).resolve().parents[3]
    result = subprocess.run(
        ["git", "show", f"{branch}:{name}"],
        cwd=repo,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode != 0:
        pytest.skip(f"{name} is not on {branch}")
    return result.stdout


class TestAnUncollectedDeviceIsNotARealReading:
    """F1: the drawer must not call an uncollected device a real reading."""

    def test_the_drawer_does_not_say_reported_no_routes_for_an_uncollected_device(self):
        """The sentence must be conditional on the device having been collected.

        "This device reported no routes. That is a real reading, not a
        missing one." is true for a device that was collected and had no
        routes. It is false for a device that was never collected, and the
        two must not look the same.
        """
        source = _branch_file(
            "feature/router-discovery-ui",
            "frontend/src/components/RouterDiscoveryPage.tsx",
        )

        # Find the sentence and what it is conditional on.
        match = re.search(
            r"device\.routes\.length === 0\s*\?\s*\((?P<block>.{0,400}?)\)",
            source,
            re.DOTALL,
        )
        assert match, "the empty-routes branch is no longer in the drawer"

        block = match.group("block")
        conditional_on_failure = (
            "device.error" in block
            or "node.error" in block
            or "not collected" in block.lower()
            or "could not be collected" in block.lower()
            or "failed" in block.lower()
        )

        assert conditional_on_failure, (
            "the drawer says 'This device reported no routes. That is a real "
            "reading, not a missing one.' purely on the route count, so a "
            "device that was never collected is described as a real reading"
        )

    def test_the_device_type_can_carry_a_failure(self):
        """The drawer's device must be able to say it was not collected."""
        source = _branch_file(
            "feature/router-discovery-ui", "frontend/src/types/routing.ts"
        )

        match = re.search(
            r"interface RouterDiscoveryDevice[^{]*\{(?P<body>.*?)\n\}", source, re.DOTALL
        )
        assert match, "RouterDiscoveryDevice is no longer in the types"

        body = match.group("body")
        has_failure_field = (
            "error" in body
            or "not_collected" in body
            or "collected" in body
        )
        assert has_failure_field, (
            "RouterDiscoveryDevice cannot say that a device was not "
            "collected, so the drawer cannot tell a failed device from a "
            "device with no routes"
        )

    def test_the_device_detail_states_whether_the_device_reported(self):
        """The sentence about the numbers must not be unconditional."""
        source = _branch_file(
            "feature/router-discovery-ui",
            "frontend/src/components/RouterDiscoveryPage.tsx",
        )
        if "These are the numbers the device reported" not in source:
            pytest.skip("the wording has changed")

        index = source.index("These are the numbers the device reported")
        window = source[max(0, index - 600):index]
        # "Collected at" is nearby and contains "collected", so the check
        # has to be for a failure, not for the word "collected".
        assert (
            "error" in window
            or "failed" in window.lower()
            or "not collected" in window.lower()
        ), (
            "the drawer says 'These are the numbers the device reported' "
            "without checking whether the device reported anything"
        )


class TestAFindingCarriesItsProvenance:
    """F2: a finding that rests on an inference must say so in the finding."""

    def test_the_finding_type_has_a_provenance(self):
        source = _branch_file(
            "feature/router-discovery-ui", "frontend/src/types/routing.ts"
        )

        match = re.search(
            r"interface RouterDiscoveryFinding[^{]*\{(?P<body>.*?)\n\}", source, re.DOTALL
        )
        assert match, "RouterDiscoveryFinding is no longer in the types"

        body = match.group("body")
        assert "provenance" in body, (
            "RouterDiscoveryFinding has no provenance, so a finding that "
            "rests on an inference cannot say so"
        )

    def test_the_finding_is_rendered_with_its_provenance(self):
        source = _branch_file(
            "feature/router-discovery-ui",
            "frontend/src/components/RouterDiscoveryPage.tsx",
        )
        if "RouterDiscoveryFinding" not in source:
            pytest.skip("the findings are not rendered yet")

        assert re.search(
            r"finding\.provenance", source
        ), (
            "the finding's provenance is in the type but is not shown, so a "
            "reader has to know to look for it"
        )


class TestALimitIsVisibleInTheResult:
    """D1: a run that stopped at a limit must say it stopped."""

    def test_the_result_records_that_a_limit_was_reached(self):
        """The depth limit currently says nothing at all."""
        try:
            from app.router_discovery.engine import discover
            from app.router_discovery.models import DeviceSnapshot, RouteEntry
        except ImportError:
            pytest.skip("the router discovery module has not landed in this branch")

        class Collector:
            def __init__(self):
                self.n = 0

            def collect(self, target):
                self.n += 1
                device = DeviceSnapshot(
                    device_id=f"d{self.n}",
                    hostname=f"h{self.n}",
                    mgmt_target=target,
                    method="local",
                    collected_at="2026-10-22T00:00:00Z",
                )
                device.routes = [
                    RouteEntry(
                        prefix="10.0.0.0/8",
                        next_hop=f"10.0.0.{self.n + 1}",
                        interface="eth0",
                    )
                ]
                return device

        lines = []
        result = discover(
            seeds=["10.0.0.1"],
            collector=Collector(),
            scope="10.0.0.0/8",
            max_depth=1,
            progress=lines.append,
        )

        mentioned = any(
            "depth" in line.lower() or "limit" in line.lower() for line in lines
        )
        assert mentioned, (
            "the depth limit produced no message at all; a run that was "
            f"truncated looks exactly like a complete one. Progress was: {lines}"
        )

        fields = list(type(result).__dataclass_fields__)
        assert any(
            "limit" in field or "truncat" in field or "stopped" in field
            for field in fields
        ), (
            f"the result carries no record that a limit was reached. "
            f"DiscoveryResult has {fields}"
        )
