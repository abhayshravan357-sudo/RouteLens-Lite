"""
API tests for authorised host discovery.

The important behaviour is the guard: without a matching confirmation,
nothing is probed, and the refusal is recorded.
"""

import pytest
from httpx import AsyncClient, ASGITransport

from app.main import app
from app.discovery import discovery_service


def _client():
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest.fixture(autouse=True)
def _clear_audit():
    discovery_service._audit.clear()
    yield
    discovery_service._audit.clear()


class TestDiscoveryAPI:
    """Tests for /api/discovery endpoints."""

    @pytest.mark.asyncio
    async def test_scope_preview_describes_without_probing(self):
        """Previewing a scope shows what would be probed."""
        async with _client() as client:
            response = await client.post(
                "/api/discovery/scope",
                json={"target": "192.168.190.0/29", "max_hosts": 8},
            )
        assert response.status_code == 200
        data = response.json()
        assert data["scope"]["network"] == "192.168.190.0/29"
        assert len(data["addresses"]) == 6
        assert data["requires_confirmation"] is True
        # Nothing was probed.
        assert discovery_service.audit_trail == []

    @pytest.mark.asyncio
    async def test_scope_preview_refuses_a_wide_network(self):
        """A network larger than the limit is refused."""
        async with _client() as client:
            response = await client.post(
                "/api/discovery/scope",
                json={"target": "10.0.0.0/8"},
            )
        assert response.status_code == 400
        # The refusal is recorded.
        assert discovery_service.audit_trail[-1].outcome.value == "refused"

    @pytest.mark.asyncio
    async def test_running_without_confirmation_is_refused(self):
        """Without a confirmation nothing is probed."""
        async with _client() as client:
            response = await client.post(
                "/api/discovery/run",
                json={"target": "192.168.191.0/29", "confirmed": False},
            )
        assert response.status_code == 403
        assert "confirmation" in response.json()["detail"].lower()
        assert discovery_service.audit_trail[-1].outcome.value == "refused"
        assert discovery_service.audit_trail[-1].confirmed is False

    @pytest.mark.asyncio
    async def test_running_with_a_mismatched_confirmation_is_refused(self):
        """The confirmation has to quote the target back."""
        async with _client() as client:
            response = await client.post(
                "/api/discovery/run",
                json={
                    "target": "192.168.192.0/29",
                    "confirmed": True,
                    "confirmation": "192.168.199.0/29",
                },
            )
        assert response.status_code == 403
        assert discovery_service.audit_trail[-1].outcome.value == "refused"

    @pytest.mark.asyncio
    async def test_running_with_a_matching_confirmation_is_allowed(self, monkeypatch):
        """
        A matching confirmation lets the scan run.

        The probe is mocked. This test is about the confirmation gate, and a
        college project's test suite should not emit real ICMP probes at the
        network to prove that. The probe itself is exercised separately, in
        test_discovery.py, against a local reader.
        """
        probed = []

        async def fake_probe(self, address, timeout):
            probed.append(address)
            return None

        monkeypatch.setattr(type(discovery_service), "_probe", fake_probe)

        async with _client() as client:
            response = await client.post(
                "/api/discovery/run",
                json={
                    "target": "192.168.193.0/29",
                    "confirmed": True,
                    "confirmation": "192.168.193.0/29",
                    "interval": 0.05,
                    "timeout": 0.2,
                },
            )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] in ("completed", "failed")
        assert data["scan_id"]
        assert "hosts" in data
        # The run is recorded as confirmed.
        assert discovery_service.audit_trail[-1].outcome.value == "completed"
        assert discovery_service.audit_trail[-1].confirmed is True
        # The gate let the scan through, and the scan used the mocked probe.
        assert probed, "the confirmed scan did not probe anything"

    @pytest.mark.asyncio
    async def test_audit_trail_is_readable(self):
        """The audit trail is a list of records."""
        async with _client() as client:
            await client.post(
                "/api/discovery/scope",
                json={"target": "10.0.0.0/8"},
            )
            response = await client.get("/api/discovery/audit")
        assert response.status_code == 200
        trail = response.json()
        assert len(trail) == 1
        assert trail[0]["target"] == "10.0.0.0/8"
        assert trail[0]["outcome"] == "refused"
        assert trail[0]["timestamp"].endswith("Z")

    @pytest.mark.asyncio
    async def test_cancel_returns_the_scan_id(self):
        """Cancelling names the scan it stopped."""
        async with _client() as client:
            response = await client.post(
                "/api/discovery/cancel",
                params={"scan_id": "abc123"},
            )
        assert response.status_code == 200
        assert response.json()["scan_id"] == "abc123"
        assert response.json()["cancelled"] is True

    @pytest.mark.asyncio
    async def test_an_invalid_target_is_refused(self):
        """A malformed target never reaches the network."""
        async with _client() as client:
            response = await client.post(
                "/api/discovery/run",
                json={
                    "target": "192.168.194.0/24; rm -rf /",
                    "confirmed": True,
                    "confirmation": "192.168.194.0/24; rm -rf /",
                },
            )
        assert response.status_code == 400
        assert discovery_service.audit_trail[-1].outcome.value == "refused"
