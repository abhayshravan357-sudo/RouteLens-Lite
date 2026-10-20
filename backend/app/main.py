"""
RouteLens Lite - FastAPI Backend Application

This module creates the FastAPI application instance and defines the API routes.
It's designed to be beginner-friendly with clear structure and comments.
"""

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from app.routing import RouteLookupResult, RoutingEntry, SAMPLE_ROUTES
from app.routing_logic import lookup_route

app = FastAPI(
    title="RouteLens Lite API",
    description="A simple IPv4 routing table analyzer for a college project",
    version="0.1.0",
)

# CORS middleware allows the frontend (running on a different port) to call this API
# In production, you'd restrict origins to your actual frontend domain
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allow all origins for development
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health", tags=["Health"])
async def health_check():
    """
    Health check endpoint.

    Returns a simple JSON response indicating the service is running.
    This is useful for:
    - Load balancers to check if the service is healthy
    - Monitoring systems
    - Quick verification during development

    Returns:
        dict: A JSON object with status and service name
    """
    return {"status": "ok", "service": "RouteLens Lite API"}


@app.get("/lookup", response_model=RouteLookupResult, tags=["Routing"])
async def route_lookup(
    destination: str = Query(..., description="Destination IPv4 address to look up (e.g., 192.168.1.50)")
):
    """
    Look up the best route for a destination IPv4 address.

    Uses the routing table to find the most specific matching route
    using longest-prefix match, with metric as tiebreaker.

    Args:
        destination: The destination IPv4 address (e.g., "192.168.1.50")

    Returns:
        RouteLookupResult with the matched route and explanation
    """
    result = lookup_route(destination, SAMPLE_ROUTES)

    if result.error:
        # Return 400 for invalid input
        if "Invalid" in result.error:
            raise HTTPException(status_code=400, detail=result.error)
        else:
            raise HTTPException(status_code=404, detail=result.explanation)

    if not result.matched:
        # No matching route found
        raise HTTPException(status_code=404, detail=result.explanation)

    return result


@app.get("/routes", tags=["Routing"])
async def list_routes():
    """
    List all sample routing table entries.

    Returns:
        List of routing entries
    """
    return SAMPLE_ROUTES