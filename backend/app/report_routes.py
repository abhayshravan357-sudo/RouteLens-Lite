"""
RouteLens Lite - Report API

Exports what was measured as a report a student can keep.
"""

from fastapi import APIRouter, HTTPException
from fastapi.responses import PlainTextResponse

from app.report import build_report

router = APIRouter(prefix="/api/report", tags=["report"])


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
