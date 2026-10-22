"""
API tests for the scenario endpoints.
"""

import pytest
from httpx import AsyncClient, ASGITransport

from app.main import app


def _client():
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


class TestScenarioAPI:
    """Tests for /api/scenarios endpoints."""

    @pytest.mark.asyncio
    async def test_list_scenarios(self):
        """The scenario list endpoint returns the predefined scenarios."""
        async with _client() as client:
            response = await client.get("/api/scenarios")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        ids = {s["id"] for s in data}
        assert "client-router-server" in ids
        assert "two-routers" in ids
        assert "loop" in ids
        assert "dual-stack" in ids

    @pytest.mark.asyncio
    async def test_get_scenario(self):
        """A single scenario can be fetched in full."""
        async with _client() as client:
            response = await client.get("/api/scenarios/client-router-server")
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == "client-router-server"
        assert len(data["nodes"]) == 3
        assert len(data["links"]) == 2

    @pytest.mark.asyncio
    async def test_get_unknown_scenario(self):
        """An unknown scenario id returns 404."""
        async with _client() as client:
            response = await client.get("/api/scenarios/does-not-exist")
        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_trace_delivered(self):
        """Tracing a reachable destination reports delivered."""
        async with _client() as client:
            response = await client.post(
                "/api/scenarios/client-router-server/trace",
                json={"src": "client", "dst": "10.0.0.2"},
            )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "delivered"
        assert data["provenance"] == "simulated"
        assert len(data["hops"]) == 3
        assert data["hops"][0]["matched"]["prefix"] == "0.0.0.0/0"

    @pytest.mark.asyncio
    async def test_trace_no_route(self):
        """Tracing an unreachable destination reports no_route."""
        async with _client() as client:
            response = await client.post(
                "/api/scenarios/two-routers/trace",
                json={"src": "client", "dst": "8.8.8.8"},
            )
        assert response.status_code == 200
        assert response.json()["status"] == "no_route"

    @pytest.mark.asyncio
    async def test_trace_loop(self):
        """Tracing through a routing loop reports loop."""
        async with _client() as client:
            response = await client.post(
                "/api/scenarios/loop/trace",
                json={"src": "r1", "dst": "203.0.113.9"},
            )
        assert response.status_code == 200
        assert response.json()["status"] == "loop"

    @pytest.mark.asyncio
    async def test_trace_invalid_destination(self):
        """An invalid destination address returns 422."""
        async with _client() as client:
            response = await client.post(
                "/api/scenarios/client-router-server/trace",
                json={"src": "client", "dst": "not-an-ip"},
            )
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_trace_unknown_source(self):
        """An unknown source node returns 404."""
        async with _client() as client:
            response = await client.post(
                "/api/scenarios/client-router-server/trace",
                json={"src": "ghost", "dst": "10.0.0.2"},
            )
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_trace_ipv6(self):
        """IPv6 traces work in the dual-stack scenario."""
        async with _client() as client:
            response = await client.post(
                "/api/scenarios/dual-stack/trace",
                json={"src": "client", "dst": "2001:db8:2::2"},
            )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "delivered"
        assert data["hops"][0]["matched"]["prefix"] == "::/0"

    @pytest.mark.asyncio
    async def test_lab_apply_dry_run(self):
        """Applying the lab without root returns the plan, not an error."""
        async with _client() as client:
            response = await client.post(
                "/api/scenarios/client-router-server/lab/apply",
                params={"dry_run": "true"},
            )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "dry_run"
        assert any("ip netns add" in c for c in data["commands"])

    @pytest.mark.asyncio
    async def test_lab_teardown_dry_run(self):
        """Teardown dry run lists the namespace deletions."""
        async with _client() as client:
            response = await client.post(
                "/api/scenarios/client-router-server/lab/teardown",
                params={"dry_run": "true"},
            )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "dry_run"
        assert any("ip netns del" in c for c in data["commands"])

    @pytest.mark.asyncio
    async def test_compare_reports_honestly(self):
        """Compare returns the simulation and an honest lab status."""
        async with _client() as client:
            response = await client.post(
                "/api/scenarios/client-router-server/compare",
                json={"src": "client", "dst": "10.0.0.2"},
            )
        assert response.status_code == 200
        data = response.json()
        assert "simulated" in data
        assert "lab" in data
        assert "agree" in data
        assert data["note"]
        if data["lab"]["status"] == "unavailable":
            assert data["agree"] is None
        else:
            assert isinstance(data["agree"], bool)

    @pytest.mark.asyncio
    async def test_set_routes_valid(self):
        """Routes can be replaced on a node."""
        async with _client() as client:
            response = await client.put(
                "/api/scenarios/client-router-server/nodes/router/routes",
                json={
                    "routes": [
                        {"prefix": "0.0.0.0/0", "dev": "eth1", "via": "10.0.0.2", "metric": 5}
                    ]
                },
            )
        assert response.status_code == 200
        data = response.json()
        router = next(n for n in data["scenario"]["nodes"] if n["id"] == "router")
        assert len(router["routes"]) == 1
        assert router["routes"][0]["metric"] == 5
        # A workspace id is returned so the edit can be traced.
        assert data["workspace"]

    @pytest.mark.asyncio
    async def test_set_routes_invalid_prefix(self):
        """An invalid prefix is rejected with 422."""
        async with _client() as client:
            response = await client.put(
                "/api/scenarios/client-router-server/nodes/router/routes",
                json={"routes": [{"prefix": "not-a-network", "dev": "eth1"}]},
            )
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_set_routes_unknown_node(self):
        """An unknown node returns 404."""
        async with _client() as client:
            response = await client.put(
                "/api/scenarios/client-router-server/nodes/ghost/routes",
                json={"routes": []},
            )
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_set_routes_does_not_mutate_shared_scenario(self):
        """Editing routes must not corrupt the shared scenario registry."""
        async with _client() as client:
            before = (await client.get("/api/scenarios/client-router-server")).json()
            router_before = next(n for n in before["nodes"] if n["id"] == "router")
            original_metric = router_before["routes"][0]["metric"]

            await client.put(
                "/api/scenarios/client-router-server/nodes/router/routes",
                json={
                    "routes": [
                        {"prefix": "0.0.0.0/0", "dev": "eth1", "via": "10.0.0.2", "metric": 999}
                    ]
                },
            )

            after = (await client.get("/api/scenarios/client-router-server")).json()
            router_after = next(n for n in after["nodes"] if n["id"] == "router")
            assert router_after["routes"][0]["metric"] == original_metric

    @pytest.mark.asyncio
    async def test_route_edit_changes_the_next_trace(self):
        """A saved route change must be visible in the next simulation."""
        async with _client() as client:
            # Before the edit, the router forwards using its directly
            # connected 10.0.0.0/24, which is more specific than any
            # default route.
            before = await client.post(
                "/api/scenarios/client-router-server/trace",
                json={"src": "client", "dst": "10.0.0.2"},
            )
            assert before.json()["status"] == "delivered"
            router_hop = before.json()["hops"][1]
            assert router_hop["matched"]["prefix"] == "10.0.0.0/24"
            assert router_hop["matched"]["source"] == "connected"

            # Now edit the router so the server is reached through a
            # more specific static route than the connected network.
            saved = await client.put(
                "/api/scenarios/client-router-server/nodes/router/routes",
                json={
                    "routes": [
                        {
                            "prefix": "10.0.0.2/32",
                            "dev": "eth1",
                            "via": "10.0.0.2",
                            "metric": 5,
                        }
                    ]
                },
            )
            assert saved.status_code == 200
            workspace = saved.json()["workspace"]

            # Tracing with the workspace uses the edited routes.
            after = await client.post(
                "/api/scenarios/client-router-server/trace",
                json={"src": "client", "dst": "10.0.0.2", "workspace": workspace},
            )
            assert after.status_code == 200
            edited_hop = after.json()["hops"][1]
            assert edited_hop["matched"]["source"] == "static"
            assert edited_hop["matched"]["prefix"] == "10.0.0.2/32"
            assert edited_hop["matched"]["metric"] == 5
            assert edited_hop["matched"]["via"] == "10.0.0.2"

            # The shared scenario still has the original connected route.
            shared = await client.post(
                "/api/scenarios/client-router-server/trace",
                json={"src": "client", "dst": "10.0.0.2"},
            )
            shared_hop = shared.json()["hops"][1]
            assert shared_hop["matched"]["source"] == "connected"

    @pytest.mark.asyncio
    async def test_unknown_workspace_is_rejected(self):
        """A workspace id that does not exist is reported clearly."""
        async with _client() as client:
            response = await client.post(
                "/api/scenarios/client-router-server/trace",
                json={"src": "client", "dst": "10.0.0.2", "workspace": "nope"},
            )
        assert response.status_code == 404
        assert "workspace" in response.json()["detail"].lower()
