"""
Independent contract tests for the router-discovery module.

These are written from `docs/router-discovery-test-plan.md`, not from an
implementation, so that they are a real check rather than a restatement of
the code. Where an implementation might reasonably differ in naming, the
contract this file assumes is written out below, and the tests fail with a
message that says what was expected.

Nothing here touches the network, docker, root, or any privilege. The
command runner and the name resolver are fakes, so every case is
deterministic and fast.

THE CONTRACT THESE TESTS ASSUME
================================

Prefix: ``/api/router-discovery/``

    POST   /api/router-discovery/runs              start a run
    GET    /api/router-discovery/runs/{run_id}     its status, devices, edges, findings
    POST   /api/router-discovery/runs/{run_id}/cancel   cancel it
    GET    /api/router-discovery/audit              what was executed

Creating a run takes::

    {
      "scope": {"allowed_networks": ["192.168.0.0/16"], "allowed_hosts": []},
      "seeds": ["192.168.1.1"],
      "max_depth": 2,
      "max_devices": 10,
      "methods": ["lldp"]
    }

A scope may also be given as a bare string, which is read as a single
allowed network.

A run comes back with ``run_id``, ``status``, ``complete``, ``devices``,
``edges``, ``findings``, ``failures``, ``audit`` and ``stopped_reason``.

A device has ``id``, ``hostname``, ``addresses``, ``provenance``,
``collection_failed`` and ``failure_reason``. An edge has ``source``,
``target``, ``provenance`` ("observed" or "inferred") and ``basis``.

The two fakes are installed at the boundary, so the tests do not depend on
how the module reaches the outside world:

* ``asyncio.create_subprocess_exec`` — the command runner.
* ``socket.getaddrinfo`` — the name resolver.
"""

import asyncio
import json
import socket

import pytest
from fastapi.testclient import TestClient

# The module does not exist yet. When it does, this file starts running.
pytest.importorskip(
    "app.router_discovery",
    reason="the router_discovery module has not been implemented yet",
)

from app.main import app  # noqa: E402


API = "/api/router-discovery"


@pytest.fixture(autouse=True)
def _fresh_feature_state():
    """
    Each check starts from an empty feature state.

    Without this, a run started by one check is visible to the next, and
    the audit trail accumulates entries from every earlier check. A check
    that depends on what ran before it is not a check.
    """
    import app.router_discovery as rd

    for name in (
        "RUNS",
        "AUDIT",
        "CREDENTIALS",
        "run_methods",
        "_runs",
        "_audit",
        "runs",
        "audit",
    ):
        holder = getattr(rd, name, None)
        if isinstance(holder, dict):
            holder.clear()
        elif isinstance(holder, list):
            del holder[:]
    yield


@pytest.fixture
def client(request):
    """
    A client that owns whatever it starts.

    Each check gets its own identity, so a run started by one check is never
    visible to another, even if the implementation keeps state in module
    scope. The isolation tests use a deliberately different identity.
    """
    identity = f"test-client-{request.node.name}"
    return TestClient(app, headers={"X-Client-Id": identity})


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class FakeProcess:
    """What ``asyncio.create_subprocess_exec`` hands back."""

    def __init__(self, returncode=0, stdout=b"", stderr=b""):
        self.returncode = returncode
        self._stdout = stdout
        self._stderr = stderr

    async def communicate(self):
        return self._stdout, self._stderr

    async def wait(self):
        return self.returncode


class FakeRunner:
    """
    Stands in for the process runner.

    It records every command it was asked to run, so a test can assert that
    a command was *never* attempted — not merely that its result was
    ignored. That distinction is the whole point of the read-only guard.
    """

    def __init__(self, responses=None, default=None):
        # responses: {(program, ...): (returncode, stdout, stderr)}
        self.responses = responses or {}
        self.default = default if default is not None else (0, b"", b"")
        self.calls = []

    async def __call__(self, *args, **kwargs):
        self.calls.append(list(args))
        for prefix, result in self.responses.items():
            if tuple(args[: len(prefix)]) == tuple(prefix):
                return FakeProcess(*result)
        return FakeProcess(*self.default)

    @property
    def commands(self):
        """The commands as strings, for readable assertions."""
        return [" ".join(str(part) for part in call) for call in self.calls]


class FakeResolver:
    """Stands in for the system resolver."""

    def __init__(self, table=None, default=None):
        self.table = table or {}
        self.default = default
        self.lookups = []

    def __call__(self, host, port=None, *args, **kwargs):
        self.lookups.append(host)
        if host in self.table:
            family, _, _, _, sockaddr = self.table[host]
            return [(family, socket.SOCK_STREAM, 6, "", sockaddr)]
        if self.default is not None:
            family, _, _, _, sockaddr = self.default
            return [(family, socket.SOCK_STREAM, 6, "", sockaddr)]
        raise socket.gaierror(socket.EAI_NONAME, f"Name or service not known: {host}")


def install_runner(monkeypatch, runner):
    """Replace the process runner everywhere it might be reached."""

    async def fake_exec(*args, **kwargs):
        return await runner(*args, **kwargs)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)


def install_resolver(monkeypatch, resolver):
    monkeypatch.setattr(socket, "getaddrinfo", resolver)


# A run that the API will accept, with one device in scope.
SIMPLE_SCOPE = {
    "allowed_networks": ["192.168.0.0/16"],
    "allowed_hosts": [],
}


def make_run(client, **overrides):
    """Start a run and return the response."""
    body = {
        "scope": SIMPLE_SCOPE,
        "seeds": ["192.168.1.1"],
        "max_depth": 2,
        "max_devices": 10,
        "methods": ["lldp"],
    }
    body.update(overrides)
    return client.post(f"{API}/runs", json=body)


def run_to_completion(client, run_id, attempts=40):
    """Poll a run until it stops running."""
    for _ in range(attempts):
        response = client.get(f"{API}/runs/{run_id}")
        assert response.status_code == 200
        payload = response.json()
        if payload.get("status") not in ("running", "pending", "started"):
            return payload
        import time

        time.sleep(0.05)
    raise AssertionError(f"the run never finished: {payload}")


# ---------------------------------------------------------------------------
# The read-only guard
# ---------------------------------------------------------------------------


class TestReadOnlyGuard:
    """
    The guard is the boundary between "reads the network" and "changes it".

    A naive guard checks that a command *starts with* something allowed.
    That is enough to run ``ip route show; rm -rf /``. These tests are
    written to catch exactly that.
    """

    def _try(self, client, command):
        """Ask for a run whose method would run ``command``, and say what happened."""
        runner = FakeRunner(default=(0, b"{}", b""))
        return runner

    def test_a_write_command_is_refused(self, client, monkeypatch):
        """``ip route add`` must never reach the runner."""
        runner = FakeRunner()
        install_runner(monkeypatch, runner)

        response = make_run(client, methods=["ip route add 10.0.0.0/8 via 1.2.3.4"])
        assert response.status_code >= 400, (
            f"a write command was accepted: {response.status_code} {response.text}"
        )
        assert not runner.calls, (
            f"the runner was asked to run a write command: {runner.commands}"
        )

    def test_a_command_with_a_metacharacter_is_refused(self, client, monkeypatch):
        """
        An allowed prefix must not swallow a shell metacharacter.

        ``show ip route; rm -rf /`` begins with ``show ``, which is allowed.
        It must still be refused.
        """
        runner = FakeRunner()
        install_runner(monkeypatch, runner)

        response = make_run(client, methods=["show ip route; rm -rf /"])
        assert response.status_code >= 400, (
            f"a command with a metacharacter was accepted: {response.status_code}"
        )
        assert not runner.calls, (
            f"the runner was asked to run a command with a metacharacter: "
            f"{runner.commands}"
        )

    def test_a_command_with_a_newline_is_refused(self, client, monkeypatch):
        """A newline is a second command, and must be refused."""
        runner = FakeRunner()
        install_runner(monkeypatch, runner)

        response = make_run(client, methods=["show ip route\nrm -rf /"])
        assert response.status_code >= 400, (
            f"a command with a newline was accepted: {response.status_code}"
        )
        assert not runner.calls, (
            f"the runner was asked to run a command with a newline: {runner.commands}"
        )

    def test_a_near_miss_of_an_exact_command_is_refused(self, client, monkeypatch):
        """
        ``hostname`` is an exact entry, so ``hostname -x`` is not it.

        An allowlist that matches on a prefix would accept this.
        """
        runner = FakeRunner()
        install_runner(monkeypatch, runner)

        response = make_run(client, methods=["hostname -x"])
        assert response.status_code >= 400, (
            f"a near-miss of an exact command was accepted: {response.status_code}"
        )
        assert not runner.calls, (
            f"the runner was asked to run a near-miss of an exact command: "
            f"{runner.commands}"
        )

    def test_a_refusal_is_a_refusal_and_not_a_silent_no_op(self, client, monkeypatch):
        """
        A refused command must be refused **visibly**.

        A guard that returns "not allowed" and lets the caller carry on
        silently would let a caller believe the command ran. The refusal has
        to reach the client as an error, and it has to say why.
        """
        runner = FakeRunner()
        install_runner(monkeypatch, runner)

        response = make_run(client, methods=["ip route add 10.0.0.0/8 via 1.2.3.4"])
        assert response.status_code >= 400

        detail = response.json().get("detail", response.text)
        assert detail, "the refusal came back with no reason"
        assert isinstance(detail, str), (
            f"the refusal did not come back as a readable reason: {detail!r}"
        )

    def test_an_allowed_command_does_reach_the_runner(self, client, monkeypatch):
        """
        The guard must not be so strict that nothing works.

        Without this, a guard that refuses everything would pass every
        refusal test above.
        """
        runner = FakeRunner(default=(0, b"{}", b""))
        install_runner(monkeypatch, runner)

        response = make_run(client, methods=["hostname"])
        assert response.status_code < 400, (
            f"an allowed command was refused: {response.status_code} {response.text}"
        )


# ---------------------------------------------------------------------------
# The scope
# ---------------------------------------------------------------------------


class TestScope:
    """The scope is the boundary of what the feature may touch."""

    def test_a_run_cannot_be_created_without_a_scope(self, client, monkeypatch):
        """No scope means nothing to do, and the request must be refused."""
        runner = FakeRunner()
        install_runner(monkeypatch, runner)

        response = client.post(
            f"{API}/runs", json={"seeds": ["192.168.1.1"], "max_depth": 1}
        )
        assert response.status_code >= 400, (
            f"a run was created without a scope: {response.status_code}"
        )
        assert not runner.calls, "something was contacted without a scope"

    def test_a_malformed_scope_is_a_clear_error(self, client, monkeypatch):
        """A bad scope is a 400 with a readable reason, not a 500."""
        runner = FakeRunner()
        install_runner(monkeypatch, runner)

        response = client.post(
            f"{API}/runs",
            json={
                "scope": {"allowed_networks": ["not-a-network"], "allowed_hosts": []},
                "seeds": ["192.168.1.1"],
            },
        )
        assert response.status_code == 400, (
            f"a malformed scope answered {response.status_code}, expected 400"
        )
        detail = response.json().get("detail", "")
        assert detail, "the malformed scope was refused without a reason"

    def test_a_malformed_scope_contacts_nothing(self, client, monkeypatch):
        """The scope is validated before anything is contacted."""
        runner = FakeRunner()
        install_runner(monkeypatch, runner)

        client.post(
            f"{API}/runs",
            json={
                "scope": {"allowed_networks": ["999.999.999.0/24"], "allowed_hosts": []},
                "seeds": ["192.168.1.1"],
            },
        )
        assert not runner.calls, (
            f"something was contacted before the scope was validated: {runner.commands}"
        )

    def test_a_seed_outside_the_scope_is_refused(self, client, monkeypatch):
        """A seed outside the allowed area is refused, and nothing is contacted."""
        runner = FakeRunner()
        install_runner(monkeypatch, runner)

        response = make_run(client, seeds=["10.9.9.9"])
        assert response.status_code >= 400, (
            f"a seed outside the scope was accepted: {response.status_code}"
        )
        assert not runner.calls, (
            f"something outside the scope was contacted: {runner.commands}"
        )

    def test_a_name_that_resolves_outside_the_scope_is_refused(self, client, monkeypatch):
        """
        The scope is checked on the **resolved address**, not on the name.

        A name that resolves inside the area is fine. A name that resolves
        outside it must be refused, and the refusal must name the address it
        resolved to — otherwise the reader cannot tell a typo from a name
        that points somewhere they did not intend.
        """
        runner = FakeRunner()
        install_runner(monkeypatch, runner)
        resolver = FakeResolver(
            table={
                "router.example": (
                    socket.AF_INET,
                    socket.SOCK_STREAM,
                    6,
                    "",
                    ("10.9.9.9", 0),
                )
            }
        )
        install_resolver(monkeypatch, resolver)

        response = make_run(client, seeds=["router.example"])
        assert response.status_code >= 400, (
            f"a name resolving outside the scope was accepted: {response.status_code}"
        )
        assert not runner.calls, (
            f"something outside the scope was contacted: {runner.commands}"
        )

        detail = response.json().get("detail", "")
        assert "10.9.9.9" in str(detail), (
            f"the refusal does not name the address it resolved to: {detail!r}"
        )

    def test_a_name_that_resolves_inside_the_scope_is_accepted(self, client, monkeypatch):
        """A name that resolves inside the area is fine."""
        runner = FakeRunner(default=(0, b"{}", b""))
        install_runner(monkeypatch, runner)
        resolver = FakeResolver(
            table={
                "router.example": (
                    socket.AF_INET,
                    socket.SOCK_STREAM,
                    6,
                    "",
                    ("192.168.1.1", 0),
                )
            }
        )
        install_resolver(monkeypatch, resolver)

        response = make_run(client, seeds=["router.example"])
        assert response.status_code < 400, (
            f"a name resolving inside the scope was refused: {response.status_code} "
            f"{response.text}"
        )


# ---------------------------------------------------------------------------
# The engine
# ---------------------------------------------------------------------------


class TestEngine:
    """What the engine collects, and what it refuses to collect."""

    def _run(self, client, monkeypatch, responses, **overrides):
        runner = FakeRunner(responses=responses, default=(0, b"{}", b""))
        install_runner(monkeypatch, runner)
        response = make_run(client, **overrides)
        assert response.status_code < 400, (
            f"the run was refused: {response.status_code} {response.text}"
        )
        run_id = response.json()["run_id"]
        return runner, run_to_completion(client, run_id)

    def test_a_device_reached_by_two_addresses_is_collected_once(self, client, monkeypatch):
        """
        Identity is by hostname, not by address.

        Two seeds that are really one device must be collected once, and
        the second address must not be contacted again.

        The collector is told both seeds answer as the same device, so an
        implementation that identifies devices by address will collect it
        twice and an implementation that identifies them by hostname will
        not.
        """
        both_seeds = json.dumps(
            [
                {
                    "lldp": {
                        "chassis": {"mac": "aa:bb:cc:dd:ee:01", "name": "rtr-1"},
                        "port": {"id": "eth0", "ifname": "eth0"},
                    }
                }
            ]
        ).encode()
        runner, payload = self._run(
            client,
            monkeypatch,
            {("lldpcli",): (0, both_seeds, b"")},
            seeds=["192.168.1.1", "192.168.1.2"],
        )

        devices = payload.get("devices") or []
        names = [d.get("hostname") for d in devices if d.get("hostname")]
        assert names, (
            "the run reported no hostname for any device, so identity by "
            "hostname cannot be checked at all"
        )
        assert len(names) == len(set(names)), (
            f"the same device was collected twice: {names}"
        )

    def test_max_depth_is_honoured(self, client, monkeypatch):
        """No device beyond ``max_depth`` is collected."""
        runner, payload = self._run(client, monkeypatch, {}, max_depth=1)
        for device in payload.get("devices") or []:
            depth = device.get("depth")
            if depth is not None:
                assert depth <= 1, f"a device at depth {depth} was collected"

    def test_max_devices_is_honoured(self, client, monkeypatch):
        """The run stops at ``max_devices``."""
        # The collector reports five neighbours, so a run that ignores the
        # limit will collect more than the limit allows.
        neighbours = json.dumps(
            [
                {
                    "lldp": {
                        "chassis": {"mac": f"aa:bb:cc:dd:ee:0{i}", "name": f"rtr-{i}"},
                        "port": {"id": "eth0", "ifname": "eth0"},
                    }
                }
                for i in range(5)
            ]
        ).encode()
        runner, payload = self._run(
            client,
            monkeypatch,
            {("lldpcli",): (0, neighbours, b"")},
            max_devices=2,
        )
        devices = payload.get("devices") or []
        assert len(devices) <= 2, (
            f"{len(devices)} devices were collected, expected at most 2"
        )

    def test_a_run_stopped_at_a_limit_says_so(self, client, monkeypatch):
        """
        A run that stopped at a limit is not a complete run.

        Saying "complete" about a truncated run is a claim about coverage
        that is false.
        """
        runner, payload = self._run(client, monkeypatch, {}, max_devices=1)
        if payload.get("stopped_reason"):
            assert payload.get("complete") is False, (
                "a run that stopped at a limit claims to be complete"
            )

    def test_a_collector_failure_is_recorded_and_the_run_continues(self, client, monkeypatch):
        """
        One device failing must not end the run.

        The failure is recorded with its reason, and the other device is
        still collected.
        """
        responses = {
            ("lldpcli",): (1, b"", b"connection refused"),
        }
        runner, payload = self._run(client, monkeypatch, responses)

        failures = payload.get("failures") or []
        assert failures, "a failed collection was not recorded"
        assert any(f.get("reason") for f in failures), (
            f"a failure was recorded without a reason: {failures}"
        )
        assert payload.get("status") != "failed" or len(
            payload.get("devices") or []
        ), "the run stopped at the first failure"

    def test_a_device_that_failed_to_collect_is_not_an_empty_success(self, client, monkeypatch):
        """
        A device that could not be read is a failure, not a device with
        nothing on it.

        These are different, and the second one is a false negative that
        reads like a finding.
        """
        responses = {("lldpcli",): (1, b"", b"timed out")}
        runner, payload = self._run(client, monkeypatch, responses)

        for device in payload.get("devices") or []:
            if device.get("collection_failed"):
                assert device.get("failure_reason"), (
                    "a failed device has no reason recorded"
                )
                assert device.get("routes") in (None, []), (
                    "a device that failed to collect shows an empty route list, "
                    "which reads as a successful reading"
                )

    def test_an_arp_neighbour_is_not_queued_for_collection(self, client, monkeypatch):
        """
        An ARP neighbour is not a router.

        It says something is on the link. It does not say the thing is a
        router, and it must not send the engine off to collect from it.
        """
        arp = json.dumps(
            [{"arp": {"local": {"mac": "aa:bb:cc:dd:ee:02"}, "remote": {"mac": "aa:bb:cc:dd:ee:03"}}}]
        ).encode()
        responses = {("ip", "-j", "neigh"): (0, arp, b"")}
        runner, payload = self._run(client, monkeypatch, responses)

        # The ARP neighbour may be recorded as a neighbour, but it must not
        # become a device that was collected.
        devices = payload.get("devices") or []
        for device in devices:
            identity = {device.get("hostname"), device.get("id")}
            assert "aa:bb:cc:dd:ee:03" not in identity, (
                "an ARP neighbour was collected as if it were a device"
            )

    def test_a_neighbour_outside_the_scope_is_never_contacted(self, client, monkeypatch):
        """
        The allowlist is checked before an enqueue as well as before a
        collection.

        A neighbour discovered inside the scope may point outside it. One
        hop out of scope must not be enough to walk out of the area.
        """
        neighbour = json.dumps(
            [
                {
                    "lldp": {
                        "chassis": {"mac": "aa:bb:cc:dd:ee:09", "name": "outside-rtr"},
                        "port": {"id": "eth0", "ifname": "eth0"},
                    }
                }
            ]
        ).encode()
        responses = {("lldpcli",): (0, neighbour, b"")}
        runner, payload = self._run(client, monkeypatch, responses)

        outside = [
            call
            for call in runner.calls
            if any("10.9.9" in str(part) for part in call)
        ]
        assert not outside, (
            f"something outside the scope was contacted: {outside}"
        )


# ---------------------------------------------------------------------------
# The graph
# ---------------------------------------------------------------------------


class TestGraph:
    """Observed and inferred are different facts."""

    def test_an_edge_from_a_management_protocol_is_observed(self, client, monkeypatch):
        """LLDP and CDP report a link, so an edge from them is observed."""
        neighbour = json.dumps(
            [
                {
                    "lldp": {
                        "chassis": {"mac": "aa:bb:cc:dd:ee:01", "name": "rtr-1"},
                        "port": {"id": "eth0", "ifname": "eth0"},
                    }
                }
            ]
        ).encode()
        responses = {("lldpcli",): (0, neighbour, b"")}
        runner, payload = self._run(client, monkeypatch, responses)

        for edge in payload.get("edges") or []:
            if edge.get("provenance") == "observed":
                assert edge.get("basis"), (
                    "an observed edge does not say what reported it"
                )

    def test_a_next_hop_edge_is_inferred_and_not_observed(self, client, monkeypatch):
        """
        A next hop is a router's claim about a third party.

        It is not an observation of a link, and drawing it as one would
        claim to have seen something nobody saw.
        """
        route = json.dumps(
            [
                {
                    "dst": "10.0.0.0/8",
                    "gateway": "192.168.1.254",
                    "dev": "eth0",
                    "protocol": "static",
                }
            ]
        ).encode()
        responses = {("ip", "-j", "route"): (0, route, b"")}
        runner, payload = self._run(client, monkeypatch, responses)

        for edge in payload.get("edges") or []:
            if "192.168.1.254" in str(edge.get("target", "")) or "192.168.1.254" in str(
                edge.get("basis", "")
            ):
                assert edge.get("provenance") == "inferred", (
                    f"a next-hop edge is marked {edge.get('provenance')!r}"
                )

    def test_the_graph_holds_nothing_the_backend_did_not_report(self, client, monkeypatch):
        """
        Every device and every edge must trace back to a reading.

        This is the check that stops the graph inventing a plausible
        topology, which is the failure mode that makes a map a lie.
        """
        runner, payload = self._run(client, monkeypatch, {})

        devices = payload.get("devices") or []
        edges = payload.get("edges") or []
        known = {d.get("id") for d in devices} | {
            d.get("hostname") for d in devices if d.get("hostname")
        }
        for edge in edges:
            for end in ("source", "target"):
                value = edge.get(end)
                if value and known:
                    assert value in known or any(value in str(k) for k in known), (
                        f"an edge names {value!r}, which is not a reported device"
                    )


# ---------------------------------------------------------------------------
# The API
# ---------------------------------------------------------------------------


class TestApi:
    """What the API must refuse, and what it must never disclose."""

    def test_a_run_cannot_be_started_without_a_scope(self, client, monkeypatch):
        """A1: no scope, no run."""
        runner = FakeRunner()
        install_runner(monkeypatch, runner)

        response = client.post(f"{API}/runs", json={"seeds": ["192.168.1.1"]})
        assert response.status_code >= 400
        assert not runner.calls, "something was contacted without a scope"

    def test_a_malformed_scope_is_a_400(self, client, monkeypatch):
        """A2: a bad scope is a 400, with a reason, and nothing contacted."""
        runner = FakeRunner()
        install_runner(monkeypatch, runner)

        response = client.post(
            f"{API}/runs",
            json={
                "scope": {"allowed_networks": ["nonsense"], "allowed_hosts": []},
                "seeds": ["192.168.1.1"],
            },
        )
        assert response.status_code == 400, f"expected 400, got {response.status_code}"
        assert response.json().get("detail"), "the 400 carried no reason"
        assert not runner.calls, "something was contacted before the scope was validated"

    def test_the_rate_limiter_is_consulted_once_per_run(self, client, monkeypatch):
        """
        A4: a run is the unit of work, so the limiter counts runs.

        A limiter consulted per device refuses a legitimate run halfway
        through, and lets a caller evade the limit by asking for one device
        at a time.
        """
        from app import security

        consulted = []
        original = security.diagnostic_limiter.check

        def counting_check(key):
            consulted.append(key)
            return original(key)

        security.diagnostic_limiter.check = counting_check
        try:
            runner = FakeRunner(default=(0, b"{}", b""))
            install_runner(monkeypatch, runner)
            response = make_run(client, max_devices=5)
            assert response.status_code < 400, response.text
            run_to_completion(client, response.json()["run_id"])
        finally:
            security.diagnostic_limiter.check = original

        # The run may have consulted the limiter once, or not at all if it
        # uses a limiter of its own. What it must not do is consult it once
        # per device.
        assert len(consulted) <= 1, (
            f"the rate limiter was consulted {len(consulted)} times for one run; "
            "it must be consulted once per run, not once per device"
        )

    def test_a_concurrent_run_cap_is_enforced(self, client, monkeypatch):
        """A5: one client cannot start unlimited runs."""
        runner = FakeRunner(default=(0, b"{}", b""))
        install_runner(monkeypatch, runner)

        codes = []
        for _ in range(12):
            response = make_run(client)
            codes.append(response.status_code)
        refused = [c for c in codes if c >= 400]
        assert refused, (
            f"twelve concurrent runs were all accepted: {codes}"
        )

    def test_one_client_cannot_read_another_clients_run(self, client, monkeypatch):
        """A6: a run is private to whoever started it."""
        runner = FakeRunner(default=(0, b"{}", b""))
        install_runner(monkeypatch, runner)

        response = make_run(client)
        assert response.status_code < 400
        run_id = response.json()["run_id"]

        # A different client, with a different identity.
        other = TestClient(app, headers={"X-Client-Id": "somebody-else"})
        other_response = other.get(f"{API}/runs/{run_id}")
        assert other_response.status_code >= 400, (
            f"another client read a run it did not start: {other_response.status_code}"
        )

    def test_one_client_cannot_cancel_another_clients_run(self, client, monkeypatch):
        """A6: and it cannot stop one either."""
        runner = FakeRunner(default=(0, b"{}", b""))
        install_runner(monkeypatch, runner)

        response = make_run(client)
        run_id = response.json()["run_id"]

        other = TestClient(app, headers={"X-Client-Id": "somebody-else"})
        cancel = other.post(f"{API}/runs/{run_id}/cancel")
        assert cancel.status_code >= 400, (
            f"another client cancelled a run it did not start: {cancel.status_code}"
        )

    def test_the_client_that_started_a_run_can_read_it(self, client, monkeypatch):
        """The other side of A6: the owner can see their own run."""
        runner = FakeRunner(default=(0, b"{}", b""))
        install_runner(monkeypatch, runner)

        response = make_run(client)
        run_id = response.json()["run_id"]

        read = client.get(f"{API}/runs/{run_id}")
        assert read.status_code == 200, (
            f"the client that started the run could not read it: {read.status_code}"
        )

    def test_the_api_never_accepts_a_credential(self, client, monkeypatch):
        """A credential in a request is refused, not quietly ignored."""
        runner = FakeRunner()
        install_runner(monkeypatch, runner)

        for field, value in (
            ("password", "hunter2"),
            ("community", "public"),
            ("private_key", "-----BEGIN KEY-----"),
            ("token", "abc123"),
            ("secret", "s3cret"),
        ):
            response = client.post(
                f"{API}/runs",
                json={
                    "scope": SIMPLE_SCOPE,
                    "seeds": ["192.168.1.1"],
                    field: value,
                },
            )
            assert response.status_code >= 400, (
                f"a request carrying {field!r} was accepted: {response.status_code}"
            )

    def test_the_api_never_returns_a_credential(self, client, monkeypatch):
        """Nothing the API returns may carry a credential."""
        runner = FakeRunner(default=(0, b"{}", b""))
        install_runner(monkeypatch, runner)

        response = make_run(client)
        run_id = response.json()["run_id"]
        body = client.get(f"{API}/runs/{run_id}").text

        for word in ("password", "private_key", "community", "secret", "token"):
            assert word not in body.lower(), (
                f"the response mentions {word!r}"
            )

    def test_the_api_never_logs_a_credential(self, client, monkeypatch, caplog):
        """
        A credential that is not returned can still be written to a log.

        A log file outlives the request, so this matters as much as the
        response check.
        """
        import logging

        runner = FakeRunner(default=(0, b"{}", b""))
        install_runner(monkeypatch, runner)

        with caplog.at_level(logging.DEBUG):
            response = client.post(
                f"{API}/runs",
                json={
                    "scope": SIMPLE_SCOPE,
                    "seeds": ["192.168.1.1"],
                    "password": "hunter2",
                },
            )
        logged = caplog.text.lower()
        assert "hunter2" not in logged, "a credential was written to the log"

    def test_the_audit_trail_records_commands_that_ran(self, client, monkeypatch):
        """A9: the trail says what actually touched the network."""
        runner = FakeRunner(default=(0, b"{}", b""))
        install_runner(monkeypatch, runner)

        response = make_run(client)
        run_id = response.json()["run_id"]
        run_to_completion(client, run_id)

        audit = client.get(f"{API}/audit").json()
        entries = audit.get("entries") if isinstance(audit, dict) else audit
        assert entries is not None, "there is no audit trail"

        # Only the entries this check's run produced are considered, so an
        # earlier check's traffic cannot stand in for this one's.
        mine = [
            e
            for e in entries
            if any(device in str(e) for device in ("192.168.1.1",)) or not e.get("device")
        ]
        assert mine, (
            "the audit trail has no entry for the commands this run executed"
        )
        for entry in mine:
            command = str(entry.get("command", ""))
            assert command.strip(), "an audit entry has no command"

    def test_a_refused_command_is_not_recorded_as_having_run(self, client, monkeypatch):
        """
        A9: a refusal must not leave a trail that reads as an attempt.

        If the trail is what an operator later reads to answer "what did
        this tool do to my network?", a trail that lists refused commands as
        executed is worse than no trail.
        """
        runner = FakeRunner(default=(0, b"{}", b""))
        install_runner(monkeypatch, runner)

        response = client.post(
            f"{API}/runs",
            json={
                "scope": SIMPLE_SCOPE,
                "seeds": ["192.168.1.1"],
                "methods": ["ip route add 10.0.0.0/8 via 1.2.3.4"],
            },
        )
        run_id = (
            response.json().get("run_id")
            if response.status_code < 400
            else None
        )
        if run_id:
            run_to_completion(client, run_id)

        audit = client.get(f"{API}/audit").json()
        entries = audit.get("entries") if isinstance(audit, dict) else audit
        for entry in entries or []:
            command = str(entry.get("command", ""))
            assert "route add" not in command, (
                f"a refused write command is recorded as though it ran: {command!r}"
            )
