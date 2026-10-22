"""
RouteLens Lite - Report API

Exports what was measured as a report a student can keep.
"""

from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

from app.report import build_report

router = APIRouter(prefix="/api/report", tags=["report"])


class ReportRequest(BaseModel):
    """Payload to build a report with optional active simulation experiment."""

    format: str = Field(default="json", description="'json' or 'markdown'")
    active_experiment: Optional[Dict[str, Any]] = Field(
        default=None, description="Active packet trace experiment and before/after comparison"
    )


@router.get("")
async def get_report(format: str = "json"):
    """
    Build a report of what was observed.

    The report records the evidence behind each claim, where it came
    from, when it was collected, and what could not be established.

    Set format=markdown for a plain-text report suitable for a file.
    """
    report = await build_report()

    if format == "markdown":
        return PlainTextResponse(
            report.to_markdown(),
            media_type="text/markdown; charset=utf-8",
            headers={
                "Content-Disposition": 'attachment; filename="routelens-report.md"'
            },
        )
    elif format == "json":
        return report.model_dump()
    else:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown format {format!r}. Use 'json' or 'markdown'.",
        )


@router.post("")
async def post_report(payload: ReportRequest):
    """
    Build a report incorporating the user's active experiment.

    Captures the exact scenario, packet trace, failure diagnostics,
    and before-and-after comparison from the active user session.
    """
    report = await build_report(active_experiment=payload.active_experiment)

    if payload.format == "markdown":
        return PlainTextResponse(
            report.to_markdown(),
            media_type="text/markdown; charset=utf-8",
            headers={
                "Content-Disposition": 'attachment; filename="routelens-report.md"'
            },
        )
    elif payload.format == "json":
        return report.model_dump()
    else:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown format {payload.format!r}. Use 'json' or 'markdown'.",
        )
