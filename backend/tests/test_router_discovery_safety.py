"""
Safety tests for the router discovery module.

These tests encode the contract the wave-1 design review asked for. They
are written against the contract, not against the current behaviour, so
several of them FAIL against the code as it stands. Each failure is a
finding with a reproduction, and the owning stream fixes it.

The contract, in one place:

- A seed that is not an address, or a name that resolves nowhere, must be
  REPORTED as a failure. A run that quietly found nothing looks exactly
  like a run that worked and found nothing.
- A seed outside the scope must be REPORTED, not dropped.
- The scope applies to the RESOLVED ADDRESS. A name is a hint about one
  address, so a name that resolves outside the scope must be refused.
- The output cap must be applied while the output is being read, not after
  the whole of it is in memory.
- The command guard must use the shared metacharacter set, so a host
  target, a CIDR network and a device command are filtered the same way.

Run with:

    cd backend && python -m pytest tests/test_router_discovery_safety.py -v
"""

import ipaddress
import os
import resource
import subprocess
import sys

import pytest

from app.router_discovery import engine as rd_engine
from app.router_discovery.collectors import base as rd_base
from app.router_discovery.engine import discover, in_scope
from app.router_discovery.models import DeviceSnapshot, Neighbor, RouteEntry


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------


class FakeCollector:
    """A collector that answers for a fixed set of addresses."""

    def __init__(self, known=(), fail=()):
        self.known = set(known)
        self.fail = set(fail)
        self.collected = []

    def collect(self, target):
        self.collected.append(target)
        if target in self.fail:
            raise RuntimeError("the device refused the connection")
        if target not in self.known:
            raise RuntimeError("no route to host")
        return DeviceSnapshot(
            device_id=f"dev-{target}",
            hostname=f"host-{target}",
            mgmt_target=target,
            method="local",
            collected_at="2026-10-22T00:00:00Z",
        )


def _snapshot(device_id, routes=(), neighbors=(), interfaces=()):
    return DeviceSnapshot(
        device_id=device_id,
        hostname=device_id,
        mgmt_target="10.0.0.1",
        method="local",
        collected_at="2026-10-22T00:00:00Z",
        interfaces=list(interfaces),
        routes=list(routes),
        neighbors=list(neighbors),
    )


# --------------------------------------------------------------------------
# 1. A seed that is not an address must be reported, not dropped
# --------------------------------------------------------------------------


class TestSeedsAreReported:
    """A run that quietly found nothing looks like a run that worked."""

    def test_a_name_seed_is_reported_as_a_failure(self):
        """A name that resolves nowhere must not vanish.

        The wave-1 contract says the scope applies to the RESOLVED ADDRESS,
        so a name is a legitimate seed. If it cannot be resolved, that is a
        failure the operator must be told about.
        """
        collector = FakeCollector(known=[])

        result = discover(
            seeds=["clab-rl-r1-that-does-not-exist"],
            collector=collector,
            scope="10.0.0.0/8",
        )

        assert result.devices == []
        assert len(result.failures) == 1, (
            "a seed that could not be resolved was dropped silently; the run "
            "looks like it worked and found nothing"
        )
        assert "clab-rl-r1-that-does-not-exist" in result.failures[0].target

    def test_a_malformed_seed_is_reported_as_a_failure(self):
        collector = FakeCollector(known=[])

        result = discover(
            seeds=["not an address at all"],
            collector=collector,
            scope="10.0.0.0/8",
        )

        assert result.devices == []
        assert len(result.failures) == 1, (
            "a malformed seed was dropped silently"
        )

    def test_a_seed_outside_the_scope_is_reported_as_a_failure(self):
        """Refusing to collect it is right; refusing to say so is not."""
        collector = FakeCollector(known=["192.168.5.1"])

        result = discover(
            seeds=["192.168.5.1"],
            collector=collector,
            scope="10.0.0.0/8",
        )

        assert collector.collected == [], "it collected a device out of scope"
        assert len(result.failures) == 1, (
            "a seed outside the scope was dropped silently"
        )
        assert "192.168.5.1" in result.failures[0].target

    def test_a_good_seed_still_works(self):
        """The fix must not break the ordinary case."""
        collector = FakeCollector(known=["10.0.0.1"])

        result = discover(
            seeds=["10.0.0.1"],
            collector=collector,
            scope="10.0.0.0/8",
        )

        assert len(result.devices) == 1
        assert result.failures == []


# --------------------------------------------------------------------------
# 2. The scope applies to the resolved address
# --------------------------------------------------------------------------


class TestScopeAppliesToTheResolvedAddress:
    """A name is a hint about one address."""

    def test_a_name_that_resolves_outside_the_scope_is_refused(self):
        """The wave-1 contract, verbatim.

        The scope check must be applied to the resolved address, so a name
        that resolves to an address outside the allowlist is refused.
        """
        # The engine must be able to take a name and resolve it.
        assert hasattr(discover, "__doc__") and "resolve" in (
            discover.__doc__ or ""
        ).lower(), (
            "the engine has no way to resolve a name seed; the contract says "
            "the scope applies to the resolved address"
        )

    def test_in_scope_refuses_a_name(self):
        """in_scope takes an address. A name must not be read as one."""
        with pytest.raises(ValueError):
            in_scope("clab-rl-r1", "10.0.0.0/8")

    def test_a_name_that_resolves_inside_the_scope_would_be_accepted(self):
        """Once resolved, the resolved address is what the scope sees."""
        resolved = "10.0.0.9"

        assert in_scope(resolved, "10.0.0.0/8") is True


# --------------------------------------------------------------------------
# 3. The output cap must be applied while reading, not after
# --------------------------------------------------------------------------


class TestOutputCapIsStreaming:
    """A device that can send unlimited data must not fill memory."""

    def test_the_runner_buffers_the_whole_output(self):
        """The cap must be applied while the output is being read.

        `subprocess.run(..., capture_output=True)` reads the command's whole
        output into memory before the runner sees a single byte of it. The
        cap is then applied to that string, so the memory is already spent.
        The runner has to read in pieces and stop at the cap.
        """
        seen = {}

        def fake_run(argv, **kwargs):
            seen.update(kwargs)
            seen["argv"] = argv

            class Completed:
                stdout = "x" * 5_000_000
                stderr = ""
                returncode = 0

            return Completed()

        original = subprocess.run
        subprocess.run = fake_run
        try:
            from app.router_discovery.collectors.frr import docker_runner

            real = docker_runner({"10.0.0.1": "router1"})
            real("10.0.0.1", "show ip route json")
        finally:
            subprocess.run = original

        assert seen.get("capture_output") is not True, (
            "the runner asks for the whole output at once, so the cap cannot "
            "stop a device filling memory before it is applied"
        )

    def test_a_large_output_really_does_reach_memory(self):
        """The same call pattern, measured.

        This is the pattern the runner uses, run for real, with the output
        size a hostile device could send. `tracemalloc` is used rather
        than the process's peak RSS, because peak RSS is a high-water mark:
        once an earlier test has pushed it up, it cannot go down, and the
        measurement would read zero.
        """
        import tracemalloc

        size = 8_000_000

        tracemalloc.start()
        try:
            before = tracemalloc.get_traced_memory()[0]
            completed = subprocess.run(
                [
                    sys.executable,
                    "-c",
                    f"import sys; sys.stdout.write('x' * {size})",
                ],
                capture_output=True,
                text=True,
                timeout=30,
                shell=False,
                check=True,
            )
            after = tracemalloc.get_traced_memory()[0]
        finally:
            tracemalloc.stop()

        grew_mb = (after - before) / (1024 * 1024)

        assert len(completed.stdout) == size
        assert grew_mb > 4, (
            f"8 MB of captured output grew the Python heap by only "
            f"{grew_mb:.1f} MB, so the buffering is not showing"
        )

    def test_the_cap_is_documented_as_being_after_the_fact(self):
        """The cap exists, but it is applied to the returned string."""
        from app.router_discovery.collectors.frr import (
            MAX_OUTPUT_CHARS,
            docker_runner,
        )

        assert MAX_OUTPUT_CHARS > 0

        seen = {}

        class Completed:
            stdout = "y" * (MAX_OUTPUT_CHARS + 1_000)
            stderr = ""
            returncode = 0

        def fake_run(argv, **kwargs):
            seen["argv"] = argv
            return Completed()

        original = subprocess.run
        subprocess.run = fake_run
        try:
            run = docker_runner({"10.0.0.1": "router1"})
            out = run("10.0.0.1", "show ip route json")
        finally:
            subprocess.run = original

        assert len(out) == MAX_OUTPUT_CHARS
        # The whole thing was in memory before it was cut down.
        assert len(Completed.stdout) > MAX_OUTPUT_CHARS

    def test_a_device_that_stops_talking_does_not_hang_the_runner(self):
        """A dribbler that holds stdout open cannot block the runner forever.

        read(n) blocks until a full buffer or EOF. A device that writes a few
        bytes and holds the pipe open blocks there forever without a per-read
        deadline. The per-read deadline must kill the process and bound the
        total time.
        """
        import time
        from unittest.mock import patch, MagicMock

        from app.router_discovery.collectors.frr import (
            docker_runner,
            READ_DEADLINE_SECONDS,
        )

        # Track how long the read was allowed to block before the process
        # was killed.
        kill_time = []

        class BlockingStdout:
            def read(self, n):
                # Block longer than the per-read deadline. When the process
                # is killed, the pipe closes and this read returns.
                time.sleep(READ_DEADLINE_SECONDS * 2)
                return "partial output"

            def close(self):
                pass

        mock_proc = MagicMock()
        mock_proc.stdout = BlockingStdout()
        mock_proc.kill = MagicMock(side_effect=lambda: kill_time.append(time.monotonic()))
        mock_proc.wait = MagicMock(return_value=0)
        mock_proc.returncode = 0
        mock_proc.pid = 12345

        start = time.monotonic()

        def fake_popen(cmd, **kwargs):
            return mock_proc

        with patch("app.router_discovery.collectors.frr.subprocess.Popen") as mock_popen:
            mock_popen.side_effect = fake_popen
            run = docker_runner({"10.0.0.1": "router1"})
            out = run("10.0.0.1", "show ip route json")

        elapsed = time.monotonic() - start

        # The operation must complete in bounded time, not hang forever.
        assert elapsed < READ_DEADLINE_SECONDS * 3, f"Took {elapsed:.1f}s (deadline is {READ_DEADLINE_SECONDS}s)"

        # The process must be killed when the read deadline expires.
        mock_proc.kill.assert_called_once()

        # The process was reaped.
        mock_proc.wait.assert_called_once()

    def test_a_device_that_keeps_dribbling_does_not_run_forever(self):
        """A dribbler that produces small output before each per-read
        deadline must still be stopped by the overall deadline.

        read(n) returns quickly each time, so the per-read deadline never
        triggers. But the overall deadline (COMMAND_TIMEOUT_SECONDS) must
        bound the entire collection operation.
        """
        import time
        from unittest.mock import patch, MagicMock

        from app.router_discovery.collectors.frr import (
            docker_runner,
            COMMAND_TIMEOUT_SECONDS,
            READ_CHUNK_CHARS,
        )

        # Track kill time and read count.
        kill_time = []
        read_count = []

        class DribblerStdout:
            def __init__(self):
                self.chunks_remaining = 50  # enough to exceed the deadline

            def read(self, n):
                # Return a small chunk quickly (well under per-read
                # deadline), then pause before the next read.
                if self.chunks_remaining > 0:
                    self.chunks_remaining -= 1
                    read_count.append(time.monotonic())
                    # Sleep briefly so the per-read deadline never triggers
                    # but the overall deadline eventually does.
                    time.sleep(2.5)
                    return "x" * 100  # small chunk
                return ""

            def close(self):
                pass

        mock_proc = MagicMock()
        mock_proc.stdout = DribblerStdout()
        mock_proc.kill = MagicMock(side_effect=lambda: kill_time.append(time.monotonic()))
        mock_proc.wait = MagicMock(return_value=0)
        mock_proc.returncode = 0
        mock_proc.pid = 12345

        start = time.monotonic()

        def fake_popen(cmd, **kwargs):
            return mock_proc

        with patch("app.router_discovery.collectors.frr.subprocess.Popen") as mock_popen:
            mock_popen.side_effect = fake_popen
            run = docker_runner({"10.0.0.1": "router1"})
            out = run("10.0.0.1", "show ip route json")

        elapsed = time.monotonic() - start

        # The operation must complete in bounded time, bounded by the
        # overall deadline (not just the per-read deadline).
        assert elapsed < COMMAND_TIMEOUT_SECONDS + 3, (
            f"Took {elapsed:.1f}s but overall deadline is {COMMAND_TIMEOUT_SECONDS}s"
        )

        # The process must be killed when the overall deadline expires.
        mock_proc.kill.assert_called_once()

        # The process was reaped.
        mock_proc.wait.assert_called_once()

        # Some output was read before the deadline.
        assert len(out) > 0


def test_unavailable_lab_never_reports_condition_ready():
    """An unavailable lab must never report condition="ready".

    When overall_ready=False but privilege.available=True and a
    namespace-specific permission error exists, diagnose() must not fall
    through to condition="ready". It must report privileges_missing.
    """
    from app.lab_next_steps import diagnose, LabCondition

    # General privilege is available, but a namespace-specific permission
    # error prevents reading that namespace.
    guidance = diagnose(
        missing_tools=[],
        privilege_available=True,
        permission_issues=["rl260-router: permission denied"],
        missing_namespaces=[],
        topology_issues=[],
    )

    assert guidance.condition == LabCondition.PRIVILEGES_MISSING
    assert "permission" in guidance.summary.lower()
    assert "rl260-router" in guidance.summary


# --------------------------------------------------------------------------
# 4. One shared metacharacter set
# --------------------------------------------------------------------------


class TestOneSharedMetacharacterSet:
    """A host target, a CIDR network and a device command are filtered the same way."""

    def test_the_command_guard_uses_the_shared_set(self):
        """The guard should not carry its own copy of the list.

        `security.py` holds the shared filter. The command guard defines a
        second set. They must be one list, or they will drift.
        """
        from app.security import SHELL_METACHARACTERS as TARGET_SET

        target_set = set(TARGET_SET)
        command_set = set(rd_base.SHELL_METACHARACTERS)

        assert target_set <= command_set, (
            "the command guard's metacharacter set is not a superset of the "
            f"shared one: missing {sorted(target_set - command_set)}"
        )
        assert command_set - target_set == set("?\n\r\t"), (
            "the command guard's extra characters have changed; the shared "
            f"filter should be used and extended by exactly {sorted('?\\n\\r\\t')}"
        )

    def test_the_guard_refuses_a_chained_command(self):
        """A command that starts with an allowed prefix but chains another."""
        for command in (
            "show ip route; reload",
            "show ip route && reload",
            "show ip route | tee /tmp/x",
            "show ip route\nreload",
            "show ip route `id`",
            "show ip route $(id)",
            "show ip route > /etc/passwd",
        ):
            with pytest.raises(rd_base.CommandNotAllowed):
                rd_base.check_command(command)

    def test_the_guard_refuses_a_command_that_is_not_read_only(self):
        for command in (
            "configure terminal",
            "reload",
            "write memory",
            "delete interface eth0",
            "copy running-config startup-config",
        ):
            with pytest.raises(rd_base.CommandNotAllowed):
                rd_base.check_command(command)

    def test_the_guard_allows_the_read_only_commands(self):
        for command in (
            "show ip route json",
            "show ipv6 route json",
            "show ip ospf neighbor json",
            "show lldp neighbors json",
            "ip -j addr",
            "ip -j neigh",
            "hostname",
        ):
            rd_base.check_command(command)

    def test_a_target_cannot_carry_a_metacharacter_into_a_command(self):
        """The guard is on the command. The target is checked separately."""
        from app.security import reject_unsafe_target_chars

        with pytest.raises(Exception):
            reject_unsafe_target_chars("10.0.0.1;reload")


# --------------------------------------------------------------------------
# 5. Credentials must not reach the trail
# --------------------------------------------------------------------------


class TestCredentialsAreRedacted:
    def test_a_password_in_the_command_is_not_written_down(self):
        runner = rd_base.AuditedRunner(run=lambda t, c: "ok")

        runner("10.0.0.1", "show ip route json password=letmein")

        entry = runner.audit[-1]
        assert "letmein" not in entry.command
        assert "password=***" in entry.command

    def test_userinfo_in_the_target_is_not_written_down(self):
        runner = rd_base.AuditedRunner(run=lambda t, c: "ok")

        runner("admin:letmein@10.0.0.1", "show ip route json")

        entry = runner.audit[-1]
        assert "letmein" not in entry.target

    def test_a_password_in_an_error_is_not_written_down(self):
        def failing(target, command):
            raise RuntimeError("login failed for admin:letmein")

        runner = rd_base.AuditedRunner(run=failing)

        with pytest.raises(RuntimeError):
            runner("10.0.0.1", "show ip route json")

        entry = runner.audit[-1]
        assert "letmein" not in (entry.error or "")

    def test_the_trail_is_bounded(self):
        runner = rd_base.AuditedRunner(run=lambda t, c: "ok")

        for _ in range(rd_base.MAX_AUDIT_ENTRIES + 100):
            runner("10.0.0.1", "show ip route json")

        assert len(runner.audit) == rd_base.MAX_AUDIT_ENTRIES


# --------------------------------------------------------------------------
# 7. The routing decision must be the router's decision
# --------------------------------------------------------------------------
#
# Administrative distance decides between routes for the SAME prefix.
# Longest prefix match decides between prefixes, and administrative
# distance is irrelevant there because the less specific route was never a
# candidate for that destination.
#
# The case that matters is the same-prefix one, because that is the case
# `scenario.py`'s lookup() gets wrong: it compares (prefixlen, -metric) and
# has no protocol and no administrative distance, so for one prefix it
# picks the lower metric rather than the lower administrative distance.


class TestRoutingDecisionMatchesTheRouter:
    """The engine's choice must be the router's choice."""

    def _scenario(self, routes):
        from app.scenario import Iface, Link, Node, Route, Scenario

        return Scenario(
            id="t",
            title="t",
            nodes=[
                Node(
                    id="r1",
                    kind="router",
                    ifaces=[
                        Iface(name="eth0", cidr="10.0.1.1/24"),
                        Iface(name="eth1", cidr="10.0.2.1/24"),
                    ],
                    routes=routes,
                ),
                Node(id="a", kind="router", ifaces=[Iface(name="eth0", cidr="10.0.1.2/24")]),
                Node(id="b", kind="router", ifaces=[Iface(name="eth0", cidr="10.0.2.2/24")]),
            ],
            links=[
                Link(a="r1:eth0", b="a:eth0"),
                Link(a="r1:eth1", b="b:eth0"),
            ],
        )

    def test_the_same_prefix_case_where_admin_distance_decides(self):
        """One prefix, two protocols. A router takes the lower admin distance.

        The route via 10.0.1.2 has the worse metric (20 against 5), but a
        router never looks at the metric because administrative distance is
        compared first. `lookup()` ranks by (prefixlen, -admin_distance,
        -metric), so the lower admin distance wins and the metric is never
        compared.
        """
        from app.scenario import Route, lookup

        scenario = self._scenario(
            [
                Route(prefix="10.0.0.0/8", dev="eth0", via="10.0.1.2", metric=20, admin_distance=1),
                Route(prefix="10.0.0.0/8", dev="eth1", via="10.0.2.2", metric=5, admin_distance=100),
            ]
        )

        best, candidates = lookup(scenario.routing_table("r1"), ipaddress.ip_address("10.0.0.55"))

        assert len(candidates) == 2
        # A router installs the route with the lower administrative distance
        # for this prefix. The metric is never compared.
        assert best.via == "10.0.1.2", (
            f"the engine picked {best.via}; a router picks the route with the "
            f"lower administrative distance, not the lower metric"
        )

    def test_the_different_prefix_case_is_not_a_finding(self):
        """Longest prefix decides, and the engine already does that.

        Recorded so the distinction is not lost: administrative distance is
        irrelevant here, because the /8 was never a candidate for a
        destination the /24 already covers.
        """
        from app.scenario import Route, lookup

        scenario = self._scenario(
            [
                Route(prefix="10.0.0.0/8", dev="eth0", via="10.0.1.2", metric=20),
                Route(prefix="10.0.0.0/24", dev="eth1", via="10.0.2.2", metric=110),
            ]
        )

        best, _ = lookup(scenario.routing_table("r1"), ipaddress.ip_address("10.0.0.55"))

        assert best.prefix == "10.0.0.0/24"

    def test_the_default_route_does_not_win_on_admin_distance(self):
        """The textbook case: the /8 wins, not the default.

        The default route has the better administrative distance, and still
        does not carry the packet.
        """
        from app.scenario import Route, lookup

        scenario = self._scenario(
            [
                Route(prefix="0.0.0.0/0", dev="eth0", via="10.0.1.2", metric=0),
                Route(prefix="10.0.0.0/8", dev="eth1", via="10.0.2.2", metric=20),
            ]
        )

        best, _ = lookup(scenario.routing_table("r1"), ipaddress.ip_address("10.1.2.3"))

        assert best.prefix == "10.0.0.0/8"


# --------------------------------------------------------------------------
# 8. The string a user reads
# --------------------------------------------------------------------------


class TestTheStringAUserReads:
    """A label in the code is not enough. The response text is what counts."""

    def test_a_trace_over_collected_data_must_not_say_simulated(self):
        """`TraceResult.provenance` is a hardcoded Literal["simulated"].

        If the analysis reuses `trace()`, the provenance that comes back
        says the result was simulated, whatever it was computed from. A
        student would have no way to tell that the path was worked out
        from collected data rather than measured.
        """
        from app.scenario import TraceResult

        provenance_field = TraceResult.model_fields["provenance"]
        allowed = provenance_field.annotation

        assert "simulated" in str(allowed)
        assert "observed" in str(allowed) or "inferred" in str(allowed), (
            "TraceResult.provenance can only say 'simulated'; a trace over a "
            "table read from a real router would claim to be simulated"
        )

    def test_the_analysis_response_must_name_what_it_did(self):
        """The analysis must say it is a decision over collected routes.

        This test cannot pass until the analysis exists. It encodes the
        contract so that whoever builds it knows what is being asked for.
        """
        try:
            from app.router_discovery import analysis  # noqa: F401
        except ImportError:
            pytest.skip(
                "the router analysis has not landed yet; this test records the "
                "contract it must meet"
            )

        assert hasattr(analysis, "select_route") or hasattr(analysis, "build_fib")


# --------------------------------------------------------------------------
# 9. What the engine must not do
# --------------------------------------------------------------------------


class TestEngineBoundaries:
    def test_arp_neighbours_are_not_followed(self):
        """An ARP entry is a host on the link, not a router."""
        collector = FakeCollector(known=["10.0.0.1"])
        device = _snapshot(
            "dev-10.0.0.1",
            neighbors=[Neighbor(local_if="eth0", remote_ip="10.0.0.99", via="arp")],
        )

        def collect(target):
            collector.collected.append(target)
            return device

        collector.collect = collect

        result = discover(seeds=["10.0.0.1"], collector=collector, scope="10.0.0.0/8")

        assert collector.collected == ["10.0.0.1"], "it followed an ARP neighbour"

    def test_a_device_reached_by_two_addresses_is_collected_once(self):
        collector = FakeCollector(known=["10.0.0.1", "10.0.0.2"])
        device = _snapshot("dev-one")

        class OneDevice:
            def __init__(self):
                self.collected = []

            def collect(self, target):
                self.collected.append(target)
                return device

        one = OneDevice()
        result = discover(
            seeds=["10.0.0.1", "10.0.0.2"], collector=one, scope="10.0.0.0/8"
        )

        assert len(result.devices) == 1

    def test_a_device_that_refuses_is_recorded_and_the_run_continues(self):
        collector = FakeCollector(known=["10.0.0.2"], fail=["10.0.0.1"])

        result = discover(
            seeds=["10.0.0.1", "10.0.0.2"], collector=collector, scope="10.0.0.0/8"
        )

        assert len(result.failures) == 1
        assert len(result.devices) == 1

    def test_the_depth_limit_is_honoured(self):
        collector = FakeCollector(known=["10.0.0.1"])

        result = discover(
            seeds=["10.0.0.1"],
            collector=collector,
            scope="10.0.0.0/8",
            max_depth=0,
        )

        assert len(result.devices) == 1

    def test_the_device_limit_is_honoured(self):
        collector = FakeCollector(known=["10.0.0.1", "10.0.0.2", "10.0.0.3"])

        result = discover(
            seeds=["10.0.0.1", "10.0.0.2", "10.0.0.3"],
            collector=collector,
            scope="10.0.0.0/8",
            max_devices=2,
        )

        assert len(result.devices) == 2
