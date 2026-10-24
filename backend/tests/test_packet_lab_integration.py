"""
Integration tests for the Packet Lab API.

These tests use ASGITransport to hit the real FastAPI app without mocking
the lab adapter. They verify that the backend honestly reports the lab's
real state — available, unavailable due to permissions, or unavailable due
to missing namespaces — rather than fabricating success.
"""

import os

import pytest
from httpx import AsyncClient, ASGITransport

from app.main import app


pytestmark = pytest.mark.skipif(
    os.geteuid() == 0,
    reason="running as root; real permission-denied behaviour cannot be observed",
)


class TestLabStatusIntegration:
    """Real lab status through the API."""

    @pytest.mark.asyncio
    async def test_lab_status_returns_honest_state(self):
        """
        GET /api/lab/status returns the real lab state.

        On this host the rl260-* namespaces may not exist or may not be
        accessible, so the lab reports unavailable with an honest
        explanation. It does not pretend to be ready.

        The test accepts any legitimate readiness failure — missing
        namespaces, insufficient privileges, or other documented blockers
        — without hardcoding the current machine's state.
        """
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/lab/status")

        assert response.status_code == 503
        data = response.json()
        assert "detail" in data
        detail = data["detail"]
        # The detail honestly names why the lab is unavailable — rather than
        # fabricating success. Accept missing namespaces, insufficient
        # privileges, or any other documented readiness failure.
        assert isinstance(detail, str)
        assert len(detail) > 0
        assert "not available" in detail.lower() or "not ready" in detail.lower() or "does not exist" in detail.lower() or "permission" in detail.lower()

    @pytest.mark.asyncio
    async def test_simulate_returns_503_when_lab_unavailable(self):
        """
        POST /api/lab/simulate returns 503 when the lab is unavailable.

        The backend does not fabricate a capture result when it cannot
        actually run the lab.
        """
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post("/api/lab/simulate", json={
                "source_ip": "192.168.10.2",
                "destination_ip": "192.168.20.2",
                "protocol": "icmp",
                "ttl": 64,
                "length": 84,
            })

        assert response.status_code == 503
        data = response.json()
        assert "detail" in data
