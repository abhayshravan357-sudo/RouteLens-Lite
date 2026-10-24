"""
API tests for the diagnostic endpoint guards.

These confirm that the endpoints refuse dangerous targets, that the rate
limiter engages, and that the CORS policy is not wide open.
"""

import pytest
from httpx import AsyncClient, ASGITransport

from app.main import ALLOWED_ORIGINS, app
from app.security import diagnostic_limiter


def _client():
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest.fixture(autouse=True)
def _reset_limiter():
    """Keep the shared limiter from leaking state between tests."""
    diagnostic_limiter.reset()
    yield
    diagnostic_limiter.reset()


class TestDiagnosticTargetValidation:
    """Dangerous targets must be refused before any command runs."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "target",
        [
            "-oProxy",
            "a;b",
            "$(id)",
            "`id`",
            "a|b",
            "host && rm -rf /",
        ],
    )
    async def test_connectivity_rejects_dangerous_target(self, target):
        """The connectivity endpoint refuses injection-shaped targets."""
        async with _client() as client:
            response = await client.post(
                "/network/connectivity",
                json={"target": target, "protocol": "icmp", "timeout": 1},
            )
        assert response.status_code == 400
        assert "detail" in response.json()

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "target",
        ["-oProxy", "a;b", "$(id)"],
    )
    async def test_traceroute_rejects_dangerous_target(self, target):
        """The traceroute endpoint refuses injection-shaped targets."""
        async with _client() as client:
            response = await client.post(
                "/network/traceroute",
                json={"target": target, "max_hops": 3, "timeout_per_hop": 1,
                      "probes_per_hop": 1, "overall_timeout": 10},
            )
        assert response.status_code == 400

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "hostname",
        ["-oProxy", "a;b", "$(id)"],
    )
    async def test_dns_rejects_dangerous_hostname(self, hostname):
        """The DNS endpoint refuses injection-shaped hostnames."""
        async with _client() as client:
            response = await client.post(
                "/network/dns-resolve",
                json={"hostname": hostname, "timeout": 1},
            )
        assert response.status_code == 400

    @pytest.mark.asyncio
    async def test_valid_target_is_accepted(self):
        """A legitimate target passes validation and reaches the collector."""
        async with _client() as client:
            response = await client.post(
                "/network/connectivity",
                json={"target": "127.0.0.1", "protocol": "tcp", "port": 9,
                      "timeout": 1},
            )
        # A refused connection is a real result, not a validation failure.
        assert response.status_code in (200, 408, 500)


class TestRateLimiting:
    """Diagnostic requests must be bounded."""

    @pytest.mark.asyncio
    async def test_repeated_requests_are_rate_limited(self):
        """Enough requests in a row trigger a 429."""
        async with _client() as client:
            statuses = []
            for _ in range(40):
                response = await client.post(
                    "/network/connectivity",
                    json={"target": "127.0.0.1", "protocol": "tcp", "port": 9,
                          "timeout": 1},
                )
                statuses.append(response.status_code)
                if response.status_code == 429:
                    break
        assert 429 in statuses, f"expected a 429 among {statuses}"


class TestCorsPolicy:
    """The CORS policy must not be open to every origin."""

    def test_origins_are_allowlisted(self):
        """Origins are an explicit list, not a wildcard."""
        assert "*" not in ALLOWED_ORIGINS
        assert ALLOWED_ORIGINS
        for origin in ALLOWED_ORIGINS:
            assert (
                origin.startswith("http://localhost")
                or origin.startswith("http://127.0.0.1")
                or origin == "https://abhayshravan357-sudo.github.io"
            )

    @pytest.mark.asyncio
    async def test_disallowed_origin_gets_no_cors_header(self):
        """A foreign origin receives no CORS allow header."""
        async with _client() as client:
            response = await client.get(
                "/health",
                headers={"Origin": "https://evil.example"},
            )
        assert "access-control-allow-origin" not in response.headers

    @pytest.mark.asyncio
    async def test_local_origin_gets_cors_header(self):
        """The local dev origin is allowed."""
        async with _client() as client:
            response = await client.get(
                "/health",
                headers={"Origin": "http://localhost:5173"},
            )
        assert response.headers.get("access-control-allow-origin") == "http://localhost:5173"
