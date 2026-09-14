"""
Response conventions shared by every MCP tool.

These matter more than the tool list. A dashboard draws a circle and the user
interprets it; an agent restates the number as prose fact, possibly into someone's
paper. So each response carries its own provenance rather than relying on
documentation the model never reads, and it never labels a value more precisely
than the pipeline can support.

Two conventions carry most of the weight:

- **Truncation is never silent.** A capped result says so, says how much is left,
  and names the tool that answers the wide version of the question. `cap_groups`
  below drops whole groups rather than trailing rows, because half a station's
  periods invites exactly the wrong conclusion about a trend.
- **Errors teach.** When a tool has no data for a request it returns the recovery
  path — what *is* available and what to try next — rather than the bare
  `404 No data in database for 2024/absorption` that
  `/api/stations/{year}/{variable}` gives the dashboard. Agents recover from the
  former and loop on the latter.
"""

from __future__ import annotations

import unicodedata
from typing import TypeVar

from pydantic import BaseModel, Field

from variables import Variable

T = TypeVar("T")

# Ceiling on one get_series answer. 144 stations x 27 years is ~3,900 rows, and
# even 20 x 30 would be ~54 KB — comparable to the whole station catalogue for a
# single call, on top of get_coverage's 19.5 KB.
MAX_SERIES_ROWS = 300
MAX_SERIES_STATIONS = 10
MAX_SERIES_PERIODS = 30

SOURCE = "EBAS / ACTRIS in-situ aerosol data, retrieved from the NILU THREDDS server over OPeNDAP"

CITATION = (
    "EBAS database, Norwegian Institute for Air Research (NILU). Data are provided by "
    "ACTRIS and the individual station principal investigators; cite the data owners "
    "and acknowledge EBAS/ACTRIS in any published use."
)

# Why these two strings exist, in the payload rather than in a docstring: an agent
# cites only what is in the tool result.
MEAN_METHOD = (
    "Annual mean of hourly values > 0. Where a station has several files for a year — "
    "usually it does — their per-file annual means are averaged unweighted, so a file "
    "covering one month counts as much as one covering twelve. Those files may also "
    "differ in size cut (PM1, PM10, or none) and in whether the sample was humidified: "
    "different measurands, not repeat measurements of one. So treat cross-station "
    "comparisons as indicative, and note that a step between two years can come from a "
    "change in which files exist rather than from the atmosphere."
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


def compress_years(years: list[int]) -> str:
    """Render a sorted year list as compact ranges: [2000, 2001, 2003] -> "2000-2001,2003".

    The station catalog carries a coverage summary for every station and variable,
    and a client caches and re-reads it. Year *lists* would roughly double the
    document for no added information — a reader needs to know which spans exist,
    not to count the members.
    """
    if not years:
        return ""
    ordered = sorted(set(years))
    spans: list[str] = []
    start = prev = ordered[0]
    for year in ordered[1:]:
        if year == prev + 1:
            prev = year
            continue
        spans.append(str(start) if start == prev else f"{start}-{prev}")
        start = prev = year
    spans.append(str(start) if start == prev else f"{start}-{prev}")
    return ",".join(spans)


def has_value(mean: float | None) -> bool:
    """The project's definition of "this station-year has data".

    `compute_annual_stats` treats a mean of zero or less as absent, and the
    dashboard is drawn that way. The MCP tools apply the same rule so a station
    that the map shows as empty is not reported here as measuring zero.
    """
    return mean is not None and mean > 0


def fold(text: str) -> str:
    """Casefold and strip diacritics, so `Hyytiala` finds `Hyytiälä`.

    Station names in EBAS carry the local spelling — Hyytiälä, Ny-Ålesund,
    Racibórz, Zürich — and nobody types those from an agent prompt.
    """
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(c for c in decomposed if not unicodedata.combining(c)).casefold().strip()


def cap_groups(
    groups: list[tuple[str, list[T]]], max_rows: int, max_groups: int
) -> tuple[list[T], int]:
    """Take whole groups until a row or group ceiling is reached.

    Returns the kept rows and the number of groups left behind. Dropping whole
    groups is the point: a station returned with only the first few of its periods
    reads as a complete record, and a model will draw a trend through it.

    A single group larger than `max_rows` is still returned whole — one station's
    series is the smallest answer that is not misleading.
    """
    kept: list[T] = []
    for index, (_, rows) in enumerate(groups):
        if index >= max_groups:
            return kept, len(groups) - index
        if kept and len(kept) + len(rows) > max_rows:
            return kept, len(groups) - index
        kept.extend(rows)
    return kept, 0


def annual_period(year: int) -> tuple[str, str]:
    """ISO start/end dates for a calendar year.

    Every period in every response is a pair of ISO dates, never a bare year
    integer — that is what lets monthly resolution slot in later without changing
    a single response shape.
    """
    return f"{year}-01-01", f"{year}-12-31"
