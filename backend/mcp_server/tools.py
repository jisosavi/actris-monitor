"""
The tools themselves.

Imports `database` and `variables` and nothing else from the app — no FastAPI, no
`main`, no route handlers. Registration with the MCP server happens in
`server.py`, so this module never imports the MCP SDK either; tools are plain
async functions returning Pydantic models.

Nothing here may reach NILU. The dashboard is one client with a 24 h cache; agents
retry, fan out and re-ask. Every tool serves from SQLite, and a missing
(period, variable) is reported as missing rather than fetched on demand.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

import database
from variables import VARIABLES

from .formatting import Provenance, VariableInfo, annual_period

# An enum from day one even with a single member: v2 adds "monthly" without
# changing any tool signature or response shape.
Resolution = Literal["annual"]


class CoveragePeriod(BaseModel):
    """One cell of the availability matrix."""

    variable: str
    period_start: str = Field(description="ISO date, inclusive.")
    period_end: str = Field(description="ISO date, inclusive.")
    resolution: Resolution = "annual"
    n_stations: int | None = Field(
        default=None,
        description=(
            "Stations that produced a usable mean for this period. Counts stations "
            "with a non-null mean, not all stations that reported. Null means the "
            "period was fetched but its summary statistics were not stored."
        ),
    )
    fetched_at: str = Field(description="When this period was retrieved from NILU (ISO 8601, UTC).")


class CoverageResult(BaseModel):
    variables: list[VariableInfo]
    periods: list[CoveragePeriod]
    resolutions_available: list[Resolution] = ["annual"]
    truncated: bool = False
    note: str | None = None
    provenance: Provenance = Provenance()


async def get_coverage() -> CoverageResult:
    """Which periods and variables this server actually holds data for.

    Call this before requesting measurements. Coverage is uneven: a station-year is
    present only if it was fetched, and this server never fetches on demand, so
    asking for a period outside the matrix returns nothing rather than triggering a
    download.

    Returns the full period x variable matrix with a station count per cell, plus
    the definition of each variable (unit, instrument, wavelength, QC level) so
    values can be described correctly without a second call.
    """
    rows = await database.get_coverage_matrix()

    periods: list[CoveragePeriod] = []
    for row in rows:
        start, end = annual_period(row["year"])
        periods.append(
            CoveragePeriod(
                variable=row["variable"],
                period_start=start,
                period_end=end,
                n_stations=row["n_stations"],
                fetched_at=row["fetched_at"],
            )
        )

    note = None
    if not periods:
        note = (
            "This server holds no measurements yet. Nothing can be fetched through "
            "MCP — population is an operator action on the REST side. Report the "
            "absence rather than retrying."
        )

    return CoverageResult(
        variables=[VariableInfo.of(v) for v in VARIABLES.values()],
        periods=periods,
        note=note,
    )
