"""
Response conventions shared by every MCP tool.

These matter more than the tool list. A dashboard draws a circle and the user
interprets it; an agent restates the number as prose fact, possibly into someone's
paper. So each response carries its own provenance rather than relying on
documentation the model never reads, and it never labels a value more precisely
than the pipeline can support.

Two conventions are deliberately not implemented yet, because nothing in v1 needs
them and unused abstractions rot:

- **Truncation.** `truncated` is part of the wire contract from day one (see
  `CoverageResult`), but the row-capping helper arrives with the first tool that
  can actually overflow — `list_stations` or `get_series`. Never truncate silently:
  the shape is `{"rows": [...], "truncated": true, "n_remaining": N, "hint": "..."}`.
- **Teaching errors.** When a tool has no data for a request, return the recovery
  path — `{"error": "no_data", "message": ..., "available_years": [...],
  "suggestion": ...}` — rather than the bare `404 No data in database for
  2024/absorption` that `/api/stations/{year}/{variable}` gives the dashboard.
  Agents recover from the former and loop on the latter.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from variables import Variable

SOURCE = "EBAS / ACTRIS in-situ aerosol data, retrieved from the NILU THREDDS server over OPeNDAP"

CITATION = (
    "EBAS database, Norwegian Institute for Air Research (NILU). Data are provided by "
    "ACTRIS and the individual station principal investigators; cite the data owners "
    "and acknowledge EBAS/ACTRIS in any published use."
)

# Why these two strings exist, in the payload rather than in a docstring: an agent
# cites only what is in the tool result.
MEAN_METHOD = (
    "Annual mean of hourly values > 0. Stations with several files in a year use an "
    "unweighted mean of per-file annual means, so a file covering one month counts as "
    "much as one covering twelve. Treat cross-station comparisons as indicative."
)

COVERAGE_BASIS = (
    "Presence only. The pipeline records whether any valid value was found for a "
    "station-year, not what fraction of the period was observed. A station with two "
    "months of data is indistinguishable here from one with twelve."
)


class Provenance(BaseModel):
    """Attached to every tool result. Paraphrase-resistant only if it travels with the data."""

    source: str = SOURCE
    qc_level: str = Field(default="lev2", description="EBAS QC level of the underlying files.")
    mean_method: str = MEAN_METHOD
    coverage_basis: str = COVERAGE_BASIS
    citation: str = CITATION


class VariableInfo(BaseModel):
    """What a variable is, in the terms an agent should repeat."""

    key: str
    label: str
    unit: str
    instrument: str
    wavelength_nm: float | None = Field(
        default=None,
        description=(
            "Target wavelength in nm; null where the variable has no wavelength "
            "dimension. Selection from source files is nearest-neighbour without a "
            "tolerance check, so an individual file may carry a nearby wavelength."
        ),
    )
    qc_level: str

    @classmethod
    def of(cls, v: Variable) -> VariableInfo:
        return cls(
            key=v.key,
            label=v.label,
            unit=v.unit,
            instrument=", ".join(v.instruments),
            wavelength_nm=v.wavelength_nm,
            qc_level=v.qc_level,
        )


def annual_period(year: int) -> tuple[str, str]:
    """ISO start/end dates for a calendar year.

    Every period in every response is a pair of ISO dates, never a bare year
    integer — that is what lets monthly resolution slot in later without changing
    a single response shape.
    """
    return f"{year}-01-01", f"{year}-12-31"
