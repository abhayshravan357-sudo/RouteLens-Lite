"""
Tests for the bounds on the rate limiter and on discovery.

Two classes of unbounded growth were found by an independent audit:

- The rate limiter's key map grew one entry per distinct client address
  and was never trimmed, so an unauthenticated caller could grow it
  without limit.
- Discovery recorded a cancellation for scan ids that did not exist, and
  kept every audit entry forever.

These tests cover the bounds, and the per-client behaviour the limiter's
docstring promises.
"""

import json

import pytest
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient

from app.discovery import (
    MAX_AUDIT_ENTRIES,
    AuditOutcome,
    DiscoveryScope,
    DiscoveryService,
)
from app.main import app
from app.security import (
    MAX_TRACKED_CLIENTS,
    RateLimiter,
    client_key,
    diagnostic_limiter,
    discovery_limiter,
)


# --------------------------------------------------------------------------
# The rate limiter
# --------------------------------------------------------------------------


class TestRateLimiterIsPerClient:
    """Each key gets its own budget."""

    def test_one_client_exhausting_does_not_affect_another(self):
        limiter = RateLimiter(max_requests=2, period_seconds=60)
        limiter.check("client-a")
        limiter.check("client-a")

        with pytest.raises(HTTPException):
            limiter.check("client-a")

        # A different client is unaffected.
        limiter.check("client-b")
        limiter.check("client-b")

    def test_the_key_map_holds_one_entry_per_client(self):
        limiter = RateLimiter(max_requests=10, period_seconds=60)
        limiter.check("client-a")
        limiter.check("client-b")
        limiter.check("client-c")

        assert limiter.tracked_keys == 3

    def test_an_expired_window_frees_the_key(self):
        import time

        limiter = RateLimiter(max_requests=1, period_seconds=0.01)
        limiter.check("client-a")
        time.sleep(0.02)
        limiter.check("client-a")

        # The key is still there because it was used again, but a key whose
        # window emptied and was never used again is forgotten.
        limiter.check("client-b")
        time.sleep(0.02)
        limiter.check("client-c")
        assert "client-b" not in limiter._hits


class TestRateLimiterKeyMapIsBounded:
    """The key map cannot grow without limit."""

    def test_the_key_map_never_exceeds_its_cap(self):
        limiter = RateLimiter(max_requests=10, period_seconds=60, max_keys=16)

        for i in range(200):
            limiter.check(f"client-{i}")

        assert limiter.tracked_keys <= 16

    def test_the_default_cap_is_a_sane_number(self):
        assert MAX_TRACKED_CLIENTS > 0
        assert MAX_TRACKED_CLIENTS <= 100_000

    def test_a_new_client_at_the_cap_still_gets_a_budget(self):
        """Reaching the cap drops the oldest key, it does not refuse."""
        limiter = RateLimiter(max_requests=1, period_seconds=60, max_keys=4)
        for i in range(4):
            limiter.check(f"client-{i}")

        # This would be the fifth distinct key. It must still be served.
        limiter.check("client-new")

        assert limiter.tracked_keys <= 4

    def test_the_least_recently_used_key_is_dropped_first(self):
        limiter = RateLimiter(max_requests=10, period_seconds=60, max_keys=3)
        limiter.check("oldest")
        limiter.check("middle")
        limiter.check("newest")

        # Touch "oldest" so it is no longer the least recently used.
        limiter.check("oldest")

        # A fourth key evicts "middle", not "oldest".
        limiter.check("another")
        assert "middle" not in limiter._hits
        assert "oldest" in limiter._hits


class TestClientKey:
    """The key comes from the connection, not from a header."""

    def _request(self, client_host: str, headers=None):
        from starlette.requests import Request

        scope = {
            "type": "http",
            "method": "GET",
            "path": "/",
            "headers": headers or [],
            "client": (client_host, 12345) if client_host else None,
            "server": ("testserver", 80),
            "scheme": "http",
            "query_string": b"",
        }
        return Request(scope)

    def test_the_key_pairs_the_operation_with_the_address(self):
        request = self._request("10.0.0.1")

        assert client_key(request, "dns") == "dns:10.0.0.1"

    def test_two_clients_get_two_keys(self):
        a = client_key(self._request("10.0.0.1"), "dns")
        b = client_key(self._request("203.0.113.77"), "dns")

        assert a != b

    def test_the_forwarded_header_is_not_trusted(self):
        """A client that sets the header must not get a different budget.

        If the header were believed, anyone could bypass the limit by
        varying it.
        """
        spoofed = self._request(
            "10.0.0.1",
            headers=[(b"x-forwarded-for", b"203.0.113.77")],
        )
        plain = self._request("10.0.0.1")

        assert client_key(spoofed, "dns") == client_key(plain, "dns")

    def test_a_request_with_no_client_still_gets_a_key(self):
        request = self._request(None)

        assert client_key(request, "dns") == "dns:unknown"


class TestDiagnosticEndpointsAreLimitedPerClient:
    """The endpoints, not just the limiter, must be per client."""

    @pytest.fixture(autouse=True)
    def _reset(self):
        diagnostic_limiter.reset()
        yield
        diagnostic_limiter.reset()

    async def _dns_from(self, client_host: str) -> int:
        body = json.dumps({"hostname": "localhost"}).encode()
        scope = {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": "POST",
            "scheme": "http",
            "path": "/network/dns-resolve",
            "raw_path": b"/network/dns-resolve",
            "query_string": b"",
            "root_path": "",
            "headers": [
                (b"host", b"testserver"),
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode()),
            ],
            "client": (client_host, 40000),
            "server": ("testserver", 80),
            "state": {},
        }
        messages = []

        async def receive():
            return {"type": "http.request", "body": body, "more_body": False}

        async def send(message):
            messages.append(message)

        await app(scope, receive, send)
        return next(
            (m["status"] for m in messages if m["type"] == "http.response.start"),
            None,
        )

    @pytest.mark.asyncio
    async def test_one_client_exhausting_does_not_block_another(self):
        for _ in range(21):
            await self._dns_from("10.0.0.1")

        # A completely different client is not affected.
        assert await self._dns_from("203.0.113.77") == 200

    @pytest.mark.asyncio
    async def test_the_exhausted_client_is_blocked(self):
        codes = [await self._dns_from("10.0.0.1") for _ in range(22)]

        assert 429 in codes

    @pytest.mark.asyncio
    async def test_the_limiter_tracks_the_two_clients_separately(self):
        await self._dns_from("10.0.0.1")
        await self._dns_from("203.0.113.77")

        assert diagnostic_limiter.tracked_keys == 2


# --------------------------------------------------------------------------
# Discovery
# --------------------------------------------------------------------------


class TestDiscoveryAuditTrailIsBounded:
    """The trail keeps refusals, but not without limit."""

    def test_the_trail_is_bounded(self):
        service = DiscoveryService()

        for i in range(MAX_AUDIT_ENTRIES + 200):
            service.record(
                target=f"10.0.{i // 256}.{i % 256}/32",
                outcome=AuditOutcome.REFUSED,
                reason="refused",
            )

        assert len(service.audit_trail) == MAX_AUDIT_ENTRIES

    def test_refusals_are_still_recorded(self):
        service = DiscoveryService()

        service.record(
            target="10.0.0.0/8",
            outcome=AuditOutcome.REFUSED,
            reason="scope was not confirmed by the operator",
        )

        trail = service.audit_trail
        assert len(trail) == 1
        assert trail[0].outcome == AuditOutcome.REFUSED
        assert trail[0].reason == "scope was not confirmed by the operator"

    def test_the_oldest_entries_are_dropped_first(self):
        service = DiscoveryService()

        for i in range(MAX_AUDIT_ENTRIES + 10):
            service.record(target=f"10.0.0.{i}/32", outcome=AuditOutcome.REFUSED)

        trail = service.audit_trail
        assert trail[0].target == "10.0.0.10/32"

    def test_the_bound_is_stated_in_the_code(self):
        assert MAX_AUDIT_ENTRIES > 0
        assert MAX_AUDIT_ENTRIES <= 100_000


class TestCancellingAScanThatDoesNotExist:
    """A cancellation that never happened is not recorded."""

    def test_cancel_returns_false_for_an_unknown_scan(self):
        service = DiscoveryService()

        assert service.cancel("no-such-scan") is False

    def test_cancel_does_not_grow_the_map(self):
        service = DiscoveryService()

        for i in range(100):
            service.cancel(f"no-such-scan-{i}")

        assert service._cancelled == {}

    def test_cancel_works_for_a_running_scan(self):
        service = DiscoveryService()
        service._running.add("scan-1")

        assert service.cancel("scan-1") is True
        assert service.is_cancelled("scan-1") is True

    @pytest.mark.asyncio
    async def test_a_finished_scan_forgets_its_cancellation(self):
        """The bookkeeping does not outlive the scan."""
        service = DiscoveryService()
        scope = DiscoveryScope(
            network=__import__("ipaddress").ip_network("192.0.2.0/30"),
            max_hosts=1,
            interval=0.05,
            timeout=0.1,
        )

        await service.discover(scope, "scan-2")

        assert "scan-2" not in service._running
        assert "scan-2" not in service._cancelled


class TestDiscoveryEndpoints:
    """The endpoints behave honestly."""

    @pytest.fixture
    def client(self):
        return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")

    @pytest.mark.asyncio
    async def test_cancelling_an_unknown_scan_is_a_404(self, client):
        response = await client.post(
            "/api/discovery/cancel", params={"scan_id": "never-existed"}
        )

        assert response.status_code == 404
        assert "nothing to cancel" in response.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_the_cancellation_does_not_grow_the_map(self, client):
        from app.discovery import discovery_service

        before = len(discovery_service._cancelled)
        for _ in range(20):
            await client.post(
                "/api/discovery/cancel", params={"scan_id": "never-existed"}
            )

        assert len(discovery_service._cancelled) == before

    @pytest.mark.asyncio
    async def test_a_run_is_rate_limited_per_client(self, client):
        """The most expensive endpoint is bounded."""
        discovery_limiter.reset()
        try:
            codes = []
            for _ in range(12):
                response = await client.post(
                    "/api/discovery/run",
                    json={
                        "target": "192.0.2.0/30",
                        "confirmed": False,
                        "confirmation": None,
                    },
                )
                codes.append(response.status_code)

            assert 429 in codes
        finally:
            discovery_limiter.reset()

    @pytest.mark.asyncio
    async def test_the_discovery_limiter_is_separate_from_the_diagnostic_one(self):
        assert discovery_limiter is not diagnostic_limiter
