"""
Tests for CORS origin configuration.

These tests verify that:
- Local development origins remain allowed.
- The GitHub Pages origin is allowed.
- Additional configured origins work.
- Unconfigured origins are rejected (no access-control-allow-origin header).
- The health endpoint works.
"""

import importlib

import pytest
from httpx import AsyncClient, ASGITransport


def _reload_app(monkeypatch, extra_origins: str | None = None):
    """Re-import app.main with a specific ROUTELENS_CORS_ORIGINS value."""
    if extra_origins is not None:
        monkeypatch.setenv("ROUTELENS_CORS_ORIGINS", extra_origins)
    else:
        monkeypatch.delenv("ROUTELENS_CORS_ORIGINS", raising=False)

    import app.main
    importlib.reload(app.main)
    return app.main.app


@pytest.mark.asyncio
async def test_local_origins_allowed(monkeypatch):
    """Local dev origins (localhost:5173) are allowed by default."""
    app = _reload_app(monkeypatch)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            "/health",
            headers={"origin": "http://localhost:5173"},
        )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"


@pytest.mark.asyncio
async def test_github_pages_origin_allowed(monkeypatch):
    """The GitHub Pages origin is allowed by default."""
    app = _reload_app(monkeypatch)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            "/health",
            headers={"origin": "https://abhayshravan357-sudo.github.io"},
        )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == (
        "https://abhayshravan357-sudo.github.io"
    )


@pytest.mark.asyncio
async def test_additional_configured_origin_allowed(monkeypatch):
    """An origin added via ROUTELENS_CORS_ORIGINS is allowed."""
    app = _reload_app(monkeypatch, extra_origins="https://example.com")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            "/health",
            headers={"origin": "https://example.com"},
        )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "https://example.com"


@pytest.mark.asyncio
async def test_unconfigured_origin_rejected(monkeypatch):
    """An origin not in the allowed list gets no CORS header."""
    app = _reload_app(monkeypatch)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            "/health",
            headers={"origin": "https://evil.example.com"},
        )
    assert response.status_code == 200
    # No CORS header means the browser will block the cross-origin response.
    assert "access-control-allow-origin" not in response.headers


@pytest.mark.asyncio
async def test_health_endpoint_works(monkeypatch):
    """The health endpoint returns 200 regardless of CORS config."""
    app = _reload_app(monkeypatch)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data == {"status": "ok", "service": "RouteLens Lite API"}


@pytest.mark.asyncio
async def test_no_wildcard_cors(monkeypatch):
    """CORS never allows a wildcard origin."""
    app = _reload_app(monkeypatch, extra_origins="*")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            "/health",
            headers={"origin": "https://anything.example.com"},
        )
    assert response.status_code == 200
    # "*" is filtered out, so an arbitrary origin gets no CORS header.
    assert "access-control-allow-origin" not in response.headers
