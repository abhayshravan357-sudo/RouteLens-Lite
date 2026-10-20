"""
Tests for the reverse DNS name lookup applied to neighbours.

The neighbour list used here is the real one from this machine, captured
with `ip -j neigh show`:

    [{"dst":"192.168.0.1","dev":"wlp2s0","lladdr":"e8:65:d4:5c:54:28","state":["REACHABLE"]},
     {"dst":"192.168.0.102","dev":"wlp2s0","lladdr":"ce:47:68:2a:6a:b4","state":["STALE"]},
     {"dst":"192.168.0.105","dev":"wlp2s0","state":["FAILED"]}]

Which of those addresses actually has a PTR record was checked against the
machine's own resolver, and the answers are recorded here because the
interesting cases are the ones with no name:

    192.168.0.1    -> getnameinfo with NI_NAMEREQD returns ('_gateway', '0')
    192.168.0.102  -> getnameinfo with NI_NAMEREQD raises gaierror EAI_NONAME
    192.168.0.105  -> getnameinfo with NI_NAMEREQD raises gaierror EAI_NONAME

Without NI_NAMEREQD the same two lookups return ('192.168.0.102', '0') and
('192.168.0.105', '0') - the numeric form of the address, which looks like
a hostname and is not one. That is the behaviour this module exists to
avoid.
"""

import asyncio
import json
import socket
import time

import pytest
from unittest.mock import AsyncMock, patch

from app.network_collector import (
    DEFAULT_NAME_CAP,
    DEFAULT_NAME_CONCURRENCY,
    DEFAULT_NAME_TIMEOUT,
    NetworkCollector,
    NameLookupSummary,
    NeighborInfo,
    get_network_collector,
)


# Verbatim `ip -j neigh show` output from this machine.
REAL_NEIGHBORS_JSON = [
    {
        "dst": "192.168.0.1",
        "dev": "wlp2s0",
        "lladdr": "e8:65:d4:5c:54:28",
        "state": ["REACHABLE"],
    },
    {
        "dst": "192.168.0.102",
        "dev": "wlp2s0",
        "lladdr": "ce:47:68:2a:6a:b4",
        "state": ["STALE"],
    },
    {
        "dst": "192.168.0.105",
        "dev": "wlp2s0",
        "state": ["FAILED"],
    },
]

# The address on this machine that does have a PTR record.
REAL_ADDRESS_WITH_NAME = "192.168.0.1"
REAL_NAME = "_gateway"

# The addresses on this machine that have no PTR record.
REAL_ADDRESSES_WITHOUT_NAME = ["192.168.0.102", "192.168.0.105"]


def make_neighbors(count: int, prefix: str = "10.9.0") -> list[NeighborInfo]:
    """Build a list of neighbour entries for testing the cap."""
    return [
        NeighborInfo(
            ip_address=f"{prefix}.{i}",
            interface="wlp2s0",
            mac_address="aa:bb:cc:dd:ee:%02x" % (i % 256),
            state="STALE",
        )
        for i in range(count)
    ]


def _looks_like_an_address(value: str) -> bool:
    """Whether a string is an IP address rather than a name."""
    try:
        socket.inet_aton(value)
        return True
    except OSError:
        pass
    try:
        socket.inet_pton(socket.AF_INET6, value)
        return True
    except OSError:
        return False


class TestBlockingLookup:
    """The one lookup, and the check that a name is actually a name."""

    def test_live_lookup_returns_a_name_or_a_stated_reason(self):
        """Against this machine's real resolver.

        The machine's own neighbour list is used, so the answer depends on
        the network. Whatever the resolver says, the result must be one of
        two things: a real name, or a stated reason there is not one. It is
        never the address repeated back.
        """
        name, error = NetworkCollector._lookup_name_blocking(REAL_ADDRESS_WITH_NAME)

        assert (name is None) != (error is None), "exactly one of name or error"
        if name is not None:
            assert name != REAL_ADDRESS_WITH_NAME
            assert not _looks_like_an_address(name)
        else:
            assert error

    def test_live_lookup_without_ni_namereqd_would_masquerade(self):
        """Records why NI_NAMEREQD is required, using the real resolver.

        For an address with no PTR record, the plain call returns the
        numeric form. That is the string this module must never present as
        a hostname.
        """
        for address in REAL_ADDRESSES_WITHOUT_NAME:
            try:
                plain = socket.getnameinfo((address, 0), 0)
            except socket.gaierror:
                continue

            assert plain[0] == address, (
                f"{address} unexpectedly has a PTR record; this machine's "
                f"neighbour list has changed and the fixture needs updating"
            )

            # With the flag, the same address is an error rather than a name.
            with pytest.raises(socket.gaierror):
                socket.getnameinfo((address, 0), socket.NI_NAMEREQD)

            name, error = NetworkCollector._lookup_name_blocking(address)
            assert name is None
            assert error is not None

    def test_address_with_a_ptr_record_returns_the_name(self):
        """The recorded answer for this machine, checked when it holds.

        The PTR record for 192.168.0.1 came from the network this machine is
        on. A network change removes it, so the test is skipped rather than
        failed when it is gone.
        """
        name, error = NetworkCollector._lookup_name_blocking(REAL_ADDRESS_WITH_NAME)

        if name is None:
            pytest.skip(
                f"the live resolver has no PTR record for {REAL_ADDRESS_WITH_NAME} "
                f"any more ({error}); this machine's network changed"
            )

        assert name == REAL_NAME
        assert error is None

    def test_address_without_a_ptr_record_reports_no_name(self):
        for address in REAL_ADDRESSES_WITHOUT_NAME:
            name, error = NetworkCollector._lookup_name_blocking(address)

            assert name is None
            assert error is not None
            assert "no PTR record" in error or "not answering" in error

    def test_ni_namereqd_is_used(self):
        """Without NI_NAMEREQD the address comes back as its own name.

        This asserts the flag is actually passed, because the difference
        between a name and the numeric form is invisible from the result
        alone.
        """
        with patch("socket.getnameinfo") as mock:
            mock.side_effect = socket.gaierror(socket.EAI_NONAME, "Name or service not known")

            NetworkCollector._lookup_name_blocking("192.168.0.105")

            assert mock.call_args[0][1] & socket.NI_NAMEREQD

    def test_numeric_answer_is_rejected_as_a_name(self):
        """A resolver that returns the address again has not named it."""
        with patch("socket.getnameinfo", return_value=("192.168.0.105", "0")):
            name, error = NetworkCollector._lookup_name_blocking("192.168.0.105")

        assert name is None
        assert "numeric address" in error

    def test_numeric_answer_in_another_notation_is_rejected(self):
        """The same address written differently is still the address."""
        with patch("socket.getnameinfo", return_value=("::1", "0")):
            name, error = NetworkCollector._lookup_name_blocking("0:0:0:0:0:0:0:1")

        assert name is None
        assert "numeric address" in error

    def test_empty_name_is_rejected(self):
        with patch("socket.getnameinfo", return_value=("", "0")):
            name, error = NetworkCollector._lookup_name_blocking("192.168.0.105")

        assert name is None
        assert "empty name" in error

    def test_temporary_resolver_failure_is_distinguished(self):
        with patch(
            "socket.getnameinfo",
            side_effect=socket.gaierror(socket.EAI_AGAIN, "Temporary failure"),
        ):
            name, error = NetworkCollector._lookup_name_blocking("192.168.0.105")

        assert name is None
        assert "not answering" in error

    def test_unexpected_exception_is_caught(self):
        with patch("socket.getnameinfo", side_effect=RuntimeError("boom")):
            name, error = NetworkCollector._lookup_name_blocking("192.168.0.105")

        assert name is None
        assert "failed" in error


class TestResolveNeighbourNames:
    """The batch lookup: bounded, concurrent, capped, and never fatal."""

    @pytest.fixture
    def collector(self):
        return NetworkCollector(command_timeout=1.0)

    @pytest.mark.asyncio
    async def test_real_neighbour_with_a_name_is_named(self, collector):
        """The live resolver, and the contract it has to meet either way."""
        neighbors = [
            NeighborInfo(ip_address=REAL_ADDRESS_WITH_NAME, interface="wlp2s0", state="REACHABLE")
        ]

        summary = await collector.resolve_neighbour_names(neighbors)

        neighbor = neighbors[0]
        if neighbor.hostname is None:
            # The network changed and the PTR record is gone. The result
            # still has to say why there is no name.
            assert neighbor.name_provenance == "unknown"
            assert neighbor.name_error
            assert summary.found == 0
        else:
            assert neighbor.hostname == REAL_NAME
            assert neighbor.name_provenance == "inferred"
            assert neighbor.name_error is None
            assert summary.found == 1

        assert summary.attempted == 1

    @pytest.mark.asyncio
    async def test_real_neighbour_without_a_name_is_reported_as_having_none(self, collector):
        neighbors = [
            NeighborInfo(ip_address=address, interface="wlp2s0", state="STALE")
            for address in REAL_ADDRESSES_WITHOUT_NAME
        ]

        summary = await collector.resolve_neighbour_names(neighbors)

        for neighbor in neighbors:
            assert neighbor.hostname is None
            assert neighbor.name_provenance == "unknown"
            assert neighbor.name_error is not None

        assert summary.found == 0
        assert summary.no_name == 2

    @pytest.mark.asyncio
    async def test_the_address_is_never_repeated_back_as_a_name(self, collector):
        """The failure this whole feature exists to avoid."""
        neighbors = [
            NeighborInfo(ip_address="192.168.0.105", interface="wlp2s0", state="FAILED")
        ]

        await collector.resolve_neighbour_names(neighbors)

        assert neighbors[0].hostname != "192.168.0.105"
        assert neighbors[0].hostname is None

    @pytest.mark.asyncio
    async def test_name_provenance_is_inferred_not_observed(self, collector):
        """The address was observed; the name was looked up."""
        neighbors = [
            NeighborInfo(ip_address=REAL_ADDRESS_WITH_NAME, interface="wlp2s0", state="REACHABLE")
        ]

        await collector.resolve_neighbour_names(neighbors)

        assert neighbors[0].name_provenance == "inferred"
        assert neighbors[0].name_provenance != "observed"

    @pytest.mark.asyncio
    async def test_the_cap_is_applied_and_reported(self, collector):
        neighbors = make_neighbors(10)

        with patch.object(
            NetworkCollector, "_lookup_name_blocking", return_value=("host.example", None)
        ):
            summary = await collector.resolve_neighbour_names(neighbors, cap=4)

        assert summary.attempted == 4
        assert summary.skipped == 6
        assert summary.cap_reached is True
        assert summary.cap == 4

        # The ones that were looked up are named.
        assert all(n.hostname == "host.example" for n in neighbors[:4])
        # The ones past the cap are not, and say why.
        for neighbor in neighbors[4:]:
            assert neighbor.hostname is None
            assert neighbor.name_provenance == "not_looked_up"
            assert "cap" in neighbor.name_error

    @pytest.mark.asyncio
    async def test_lookups_run_concurrently(self, collector):
        """They must not run one at a time."""
        neighbors = make_neighbors(6)
        in_flight = 0
        peak = 0

        def slow_lookup(ip_address):
            nonlocal in_flight, peak
            in_flight += 1
            peak = max(peak, in_flight)
            time.sleep(0.05)
            in_flight -= 1
            return ("host.example", None)

        with patch.object(NetworkCollector, "_lookup_name_blocking", new=staticmethod(slow_lookup)):
            await collector.resolve_neighbour_names(neighbors, max_concurrency=6)

        assert peak > 1, "lookups ran one at a time"

    @pytest.mark.asyncio
    async def test_a_slow_lookup_does_not_hold_up_the_batch(self, collector):
        """A resolver that never answers must not delay the neighbour list."""
        neighbors = make_neighbors(3)

        def hanging_lookup(ip_address):
            time.sleep(30)
            return ("host.example", None)

        started = time.monotonic()
        with patch.object(NetworkCollector, "_lookup_name_blocking", new=staticmethod(hanging_lookup)):
            summary = await collector.resolve_neighbour_names(
                neighbors, timeout=0.5, max_concurrency=3
            )
        elapsed = time.monotonic() - started

        assert elapsed < 5, f"the batch waited {elapsed:.1f}s for a hanging resolver"
        assert summary.found == 0
        assert summary.no_name == 3
        for neighbor in neighbors:
            assert neighbor.hostname is None
            assert "timed out" in neighbor.name_error

    @pytest.mark.asyncio
    async def test_a_failing_lookup_does_not_fail_the_collection(self, collector):
        """The neighbour data is the point; the name is a bonus."""
        neighbors = make_neighbors(3)

        with patch.object(
            NetworkCollector, "_lookup_name_blocking", side_effect=RuntimeError("boom")
        ):
            summary = await collector.resolve_neighbour_names(neighbors)

        assert summary.found == 0
        for neighbor in neighbors:
            assert neighbor.ip_address
            assert neighbor.hostname is None
            assert neighbor.name_error is not None

    @pytest.mark.asyncio
    async def test_an_empty_neighbour_list_is_fine(self, collector):
        summary = await collector.resolve_neighbour_names([])

        assert summary.attempted == 0
        assert summary.found == 0
        assert summary.cap_reached is False

    @pytest.mark.asyncio
    async def test_summary_records_the_settings_used(self, collector):
        summary = await collector.resolve_neighbour_names(
            make_neighbors(1), timeout=1.5, cap=9, max_concurrency=3
        )

        assert summary.timeout_seconds == 1.5
        assert summary.cap == 9
        assert summary.max_concurrency == 3


class TestCollectNeighborsWithNames:
    """The names wired into the collection itself."""

    @pytest.fixture
    def collector(self):
        return NetworkCollector(command_timeout=1.0)

    @pytest.mark.asyncio
    async def test_collected_neighbours_carry_their_names(self, collector):
        with patch.object(collector, "_run_command", new_callable=AsyncMock) as mock_run:
            mock_run.return_value = (0, json.dumps(REAL_NEIGHBORS_JSON), "")

            result = await collector.collect_neighbors("ipv4")

        assert result.success is True
        assert len(result.data) == 3

        by_address = {n.ip_address: n for n in result.data}
        assert by_address[REAL_ADDRESS_WITH_NAME].hostname == REAL_NAME
        assert by_address[REAL_ADDRESS_WITH_NAME].name_provenance == "inferred"

        for address in REAL_ADDRESSES_WITHOUT_NAME:
            assert by_address[address].hostname is None
            assert by_address[address].name_provenance == "unknown"

    @pytest.mark.asyncio
    async def test_the_lookup_summary_is_in_the_result(self, collector):
        with patch.object(collector, "_run_command", new_callable=AsyncMock) as mock_run:
            mock_run.return_value = (0, json.dumps(REAL_NEIGHBORS_JSON), "")

            result = await collector.collect_neighbors("ipv4")

        summary = result.name_lookup
        assert summary is not None
        assert summary.attempted == 3
        assert summary.found == 1
        assert summary.no_name == 2
        assert summary.cap_reached is False

    @pytest.mark.asyncio
    async def test_names_can_be_turned_off(self, collector):
        """Turning the lookup off must not look anything up."""
        with patch.object(collector, "_run_command", new_callable=AsyncMock) as mock_run:
            mock_run.return_value = (0, json.dumps(REAL_NEIGHBORS_JSON), "")

            with patch.object(
                NetworkCollector, "_lookup_name_blocking", side_effect=AssertionError("looked up")
            ):
                result = await collector.collect_neighbors("ipv4", resolve_names=False)

        assert result.success is True
        assert len(result.data) == 3
        assert all(n.hostname is None for n in result.data)
        assert all(n.name_provenance == "not_looked_up" for n in result.data)
        assert result.name_lookup is None

    @pytest.mark.asyncio
    async def test_the_neighbour_list_is_complete_even_without_names(self, collector):
        """An unreachable resolver must not cost us any neighbours."""
        with patch.object(collector, "_run_command", new_callable=AsyncMock) as mock_run:
            mock_run.return_value = (0, json.dumps(REAL_NEIGHBORS_JSON), "")

            with patch.object(
                NetworkCollector,
                "_lookup_name_blocking",
                side_effect=socket.gaierror(socket.EAI_FAIL, "Non-recoverable failure"),
            ):
                result = await collector.collect_neighbors("ipv4")

        assert result.success is True
        assert len(result.data) == 3
        assert all(n.ip_address for n in result.data)
        assert all(n.hostname is None for n in result.data)


class TestNameLookupEndpoint:
    """GET /network/neighbors"""

    @pytest.fixture
    def client(self):
        from fastapi.testclient import TestClient
        from app.main import app

        return TestClient(app)

    def test_the_endpoint_returns_names(self, client):
        response = client.get("/network/neighbors")

        assert response.status_code == 200
        data = response.json()

        assert data["ip_version"] == "ipv4"
        assert data["name_lookup"] is not None
        assert data["name_lookup"]["attempted"] >= 0

        for neighbour in data["data"]:
            assert "hostname" in neighbour
            assert "name_provenance" in neighbour
            # A name is either a real name or absent. It is never the
            # address repeated back.
            if neighbour["hostname"] is not None:
                assert neighbour["hostname"] != neighbour["ip_address"]
                assert neighbour["name_provenance"] == "inferred"

    def test_the_endpoint_can_skip_the_lookup(self, client):
        response = client.get("/network/neighbors", params={"resolve_names": "false"})

        assert response.status_code == 200
        data = response.json()

        assert data["name_lookup"] is None
        assert all(n["hostname"] is None for n in data["data"])


class TestNameLookupSummary:
    """The summary dataclass."""

    def test_defaults(self):
        summary = NameLookupSummary()

        assert summary.attempted == 0
        assert summary.found == 0
        assert summary.no_name == 0
        assert summary.skipped == 0
        assert summary.cap_reached is False

    def test_defaults_are_sane(self):
        assert DEFAULT_NAME_TIMEOUT > 0
        assert DEFAULT_NAME_TIMEOUT <= 5
        assert DEFAULT_NAME_CAP > 0
        assert DEFAULT_NAME_CONCURRENCY > 0
        assert DEFAULT_NAME_CONCURRENCY <= DEFAULT_NAME_CAP

    def test_singleton_still_works(self):
        assert get_network_collector() is get_network_collector()
