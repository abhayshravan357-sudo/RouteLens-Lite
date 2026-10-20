"""
Tests for authorised host discovery.

Discovery reaches other machines, so these tests check the guards as
carefully as the probing: scope limits, confirmation, cancellation, rate
limiting and the audit trail.
"""

import asyncio
import pytest

from app.discovery import (
    AuditOutcome,
    DiscoveryScopeError,
    DiscoveryService,
    DiscoveryStatus,
    validate_scope,
)


class TestScopeValidation:
    """A scope must be acceptable before anything is probed."""

    def test_accepts_a_single_address(self):
        """A single address becomes a /32 scope."""
        scope = validate_scope("192.168.1.50")
        assert str(scope.network) == "192.168.1.50/32"
        assert scope.addresses() == ["192.168.1.50"]

    def test_accepts_a_cidr_network(self):
        """A CIDR network is accepted."""
        scope = validate_scope("192.168.1.0/28")
        assert str(scope.network) == "192.168.1.0/28"
        # 14 usable addresses in a /28.
        assert len(scope.addresses()) == 14

    def test_max_hosts_bounds_the_scope(self):
        """max_hosts caps how many addresses are probed."""
        scope = validate_scope("192.168.1.0/24", max_hosts=10)
        assert len(scope.addresses()) == 10
        assert scope.host_count == 256

    def test_rejects_a_scope_that_is_too_wide(self):
        """A network larger than the limit is refused."""
        with pytest.raises(DiscoveryScopeError, match="more than the limit"):
            validate_scope("10.0.0.0/8")

    def test_rejects_an_invalid_target(self):
        """A malformed target is refused."""
        for bad in ["not-a-network", "-oProxy", "192.168.1.0/24; rm -rf /"]:
            with pytest.raises(DiscoveryScopeError):
                validate_scope(bad)

    def test_rejects_ipv6(self):
        """IPv6 discovery is not supported yet."""
        with pytest.raises(DiscoveryScopeError, match="IPv4"):
            validate_scope("2001:db8::/64")

    def test_rejects_an_out_of_range_interval(self):
        """The interval must stay inside safe limits."""
        with pytest.raises(DiscoveryScopeError, match="interval"):
            validate_scope("192.168.1.0/28", interval=0.001)
        with pytest.raises(DiscoveryScopeError, match="interval"):
            validate_scope("192.168.1.0/28", interval=60)

    def test_rejects_an_out_of_range_timeout(self):
        """The timeout must stay inside safe limits."""
        with pytest.raises(DiscoveryScopeError, match="timeout"):
            validate_scope("192.168.1.0/28", timeout=0.001)
        with pytest.raises(DiscoveryScopeError, match="timeout"):
            validate_scope("192.168.1.0/28", timeout=100)

    def test_rejects_an_out_of_range_max_hosts(self):
        """max_hosts must stay inside the limit."""
        with pytest.raises(DiscoveryScopeError, match="max_hosts"):
            validate_scope("192.168.1.0/28", max_hosts=0)
        with pytest.raises(DiscoveryScopeError, match="max_hosts"):
            validate_scope("192.168.1.0/28", max_hosts=100_000)


class TestAuditTrail:
    """Every request leaves a record."""

    def test_a_refusal_is_recorded(self):
        """A refused scope is written to the trail."""
        service = DiscoveryService()
        service.record(
            target="10.0.0.0/8",
            outcome=AuditOutcome.REFUSED,
            reason="scope too wide",
            confirmed=False,
        )
        trail = service.audit_trail
        assert len(trail) == 1
        assert trail[0].outcome == AuditOutcome.REFUSED
        assert trail[0].confirmed is False
        assert trail[0].reason == "scope too wide"

    def test_a_completion_is_recorded(self):
        """A completed scan is written to the trail."""
        service = DiscoveryService()
        service.record(
            target="192.168.1.0/28",
            outcome=AuditOutcome.COMPLETED,
            hosts_found=3,
            addresses_probed=14,
            duration=4.2,
            confirmed=True,
        )
        entry = service.audit_trail[0]
        assert entry.outcome == AuditOutcome.COMPLETED
        assert entry.hosts_found == 3
        assert entry.confirmed is True
        assert entry.timestamp.endswith("Z")


class TestDiscovery:
    """The probing itself."""

    @pytest.mark.asyncio
    async def test_no_hosts_found_is_an_honest_result(self):
        """A scan where nothing answers reports zero hosts, not an error."""
        service = DiscoveryService()
        scope = validate_scope("192.168.200.0/29", interval=0.05, timeout=0.2)

        async def never_answers(address, timeout):
            return None

        service._probe = never_answers

        result = await service.discover(scope, "scan-1")
        assert result["status"] == DiscoveryStatus.COMPLETED.value
        assert result["hosts"] == []
        assert result["addresses_probed"] > 0
        assert result["cancelled"] is False

    @pytest.mark.asyncio
    async def test_hosts_that_answer_are_reported(self):
        """A host that answers is reported with its latency."""
        service = DiscoveryService()
        scope = validate_scope("192.168.201.0/29", interval=0.05, timeout=0.2)

        async def one_answers(address, timeout):
            if address.endswith(".1"):
                from app.discovery import DiscoveredHost
                return DiscoveredHost(
                    ip_address=address, method="icmp", latency_ms=1.5
                )
            return None

        service._probe = one_answers

        result = await service.discover(scope, "scan-2")
        assert result["status"] == DiscoveryStatus.COMPLETED.value
        assert len(result["hosts"]) == 1
        assert result["hosts"][0]["ip_address"].endswith(".1")
        assert result["hosts"][0]["method"] == "icmp"

    @pytest.mark.asyncio
    async def test_a_cancelled_scan_stops_early(self):
        """A cancelled scan stops probing and says so."""
        service = DiscoveryService()
        scope = validate_scope("192.168.202.0/28", interval=0.05, timeout=0.2)
        service.cancel("scan-3")

        probed = []

        async def counting_probe(address, timeout):
            probed.append(address)
            return None

        service._probe = counting_probe

        result = await service.discover(scope, "scan-3")
        assert result["status"] == DiscoveryStatus.CANCELLED.value
        assert result["cancelled"] is True
        assert probed == []
        # The cancellation is recorded.
        assert service.audit_trail[-1].outcome == AuditOutcome.CANCELLED

    @pytest.mark.asyncio
    async def test_the_rate_limit_is_respected(self):
        """Probes are spaced out, not fired all at once."""
        service = DiscoveryService()
        scope = validate_scope("192.168.203.0/29", interval=0.05, timeout=0.2)

        stamps = []

        async def timed_probe(address, timeout):
            stamps.append(asyncio.get_running_loop().time())
            return None

        service._probe = timed_probe

        await service.discover(scope, "scan-4")

        # Seven addresses, so six gaps, each at least the interval.
        assert len(stamps) >= 2
        gaps = [b - a for a, b in zip(stamps, stamps[1:])]
        assert all(gap >= 0.04 for gap in gaps), f"gaps were {gaps}"


class TestProbeSafety:
    """Probing must not be able to be turned into something else."""

    @pytest.mark.asyncio
    async def test_the_probe_passes_the_address_after_a_double_dash(self):
        """The address is passed after -- so it cannot be read as an option."""
        service = DiscoveryService()

        recorded = {}

        async def fake_exec(*args, **kwargs):
            recorded["args"] = args
            raise asyncio.TimeoutError()

        # Patch the subprocess call to capture the arguments.
        original = asyncio.create_subprocess_exec

        async def patched(*args, **kwargs):
            recorded["args"] = args
            raise asyncio.TimeoutError()

        asyncio.create_subprocess_exec = patched
        try:
            await service._probe("192.168.1.1", 0.2)
        finally:
            asyncio.create_subprocess_exec = original

        args = recorded["args"]
        assert "--" in args
        assert args[-1] == "192.168.1.1"
