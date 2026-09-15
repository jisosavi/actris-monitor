"""
The tools themselves.

Imports `database`, `variables` and `aggregation` — all pure modules — and nothing
else from the app. No FastAPI, no `main`, no route handlers. Registration with the
MCP server happens in `server.py`, so this module never imports the MCP SDK either;
tools are plain async functions returning Pydantic models.

Nothing here may reach NILU. The dashboard is one client with a 24 h cache; agents
retry, fan out and re-ask. Every tool serves from SQLite, and a missing
(period, variable) is reported as missing rather than fetched on demand.

Two rules that every tool below follows, because they are what separate a result a
model can reason about from one it will misreport:

- **Absence is stated, never implied.** A requested period with no data comes back
  with a null mean; a station that exists but holds nothing comes back flagged; a
  query that matches nothing comes back with candidates and a way forward. Silence
  is indistinguishable from "does not exist", and models resolve that ambiguity
  badly.
- **No implicit "latest".** Level 2 publication lags by a year or two, so the newest
  period is reliably the emptiest — 2026 currently holds zero stations. Any tool
  that resolves a period on the caller's behalf names the period it chose.
"""

from __future__ import annotations

import difflib
from typing import Annotated, Literal

from pydantic import BaseModel, Field

import actris_md
import database
from aggregation import compute_network_stats
from variables import VARIABLES

from .formatting import (
    MAX_SERIES_PERIODS,
    MAX_SERIES_ROWS,
    MAX_SERIES_STATIONS,
    Provenance,
    VariableInfo,
    annual_period,
    cap_groups,
    compress_years,
    fold,
    has_value,
)

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


# ── Shared filter vocabulary ──────────────────────────────────────────────────
#
# Every tool that selects stations takes the same four: stations, country,
# network, limit. Three tools with three filter shapes is three chances for a
# model to guess wrong.

VariableKey = Literal["N", "scattering", "absorption"]

StationsFilter = Annotated[
    list[str] | None,
    Field(default=None, description="EBAS station codes, e.g. ['FI0050R']. Resolve names with find_station."),
]
CountryFilter = Annotated[
    str | None,
    Field(default=None, description="Two-letter country code from the station code prefix, e.g. 'FI'."),
]
NetworkFilter = Annotated[
    str | None,
    Field(default=None, description="One of ACTRIS, EMEP, GAW-WDCA."),
]


def _matches_filters(
    country: str | None,
    network: str | None,
    row_country: str,
    row_networks: str,
) -> bool:
    if country and row_country.upper() != country.upper():
        return False
    if network and network.upper() not in {n.upper() for n in row_networks.split(",") if n}:
        return False
    return True


def _year_of(period: str | int) -> int:
    """Accept 2020, '2020' or '2020-01-01'. Annual resolution uses only the year."""
    text = str(period).strip()
    return int(text[:4])


async def _periods_with_data(variable: str) -> list[int]:
    """Years that actually hold a usable mean for a variable, ascending."""
    return sorted(
        row["year"]
        for row in await database.get_coverage_matrix()
        if row["variable"] == variable and (row["n_stations"] or 0) > 0
    )


def _no_data(variable: str, year: int, available: list[int]) -> dict:
    """The teaching-error body: what exists and what to try, not just what failed."""
    nearest = min(available, key=lambda y: abs(y - year)) if available else None
    return {
        "error": "no_data",
        "message": f"No data for {year} / {variable}.",
        "available_periods": compress_years(available) or None,
        "suggestion": (
            f"Nearest period with data is {nearest}."
            if nearest is not None
            else "This server holds no data for this variable at all; nothing to retry."
        ),
    }


# ── find_station ──────────────────────────────────────────────────────────────

class StationMatch(BaseModel):
    id: str
    name: str
    country: str = Field(description="Two-letter code from the station code prefix, not a country name.")
    lat: float
    lon: float
    networks: list[str]
    coverage: dict[str, str] = Field(
        description="Variable → years holding a usable mean, as ranges ('2000-2019,2021-2024'). Empty means the station is in the record but holds no usable value for any variable."
    )
    matched_on: str = Field(description="code, name, filter, or approximate.")
    altitude_m: float | None = Field(
        default=None,
        description="Metres above sea level, from the ACTRIS facility registry. A mountain site and a city site are not comparable.",
    )
    actris_labelling: str | None = Field(
        default=None,
        description="ACTRIS National Facility certification status: labelled, initially accepted, labelling opened/planned/application submitted, or not labelled. Current state, not a property of any period. Null when the station has no ACTRIS facility record.",
    )
    actris_active: bool | None = Field(
        default=None,
        description="Whether the facility is currently registered as operating. NOT a statement about data: a site can keep submitting to EBAS after leaving the registry, and an inactive station's historical measurements remain valid.",
    )
    actris_url: str | None = Field(default=None, description="The station's page in the ACTRIS Data Portal.")


class FindStationResult(BaseModel):
    matches: list[StationMatch]
    n_matched: int
    truncated: bool = False
    n_remaining: int = 0
    hint: str | None = None
    note: str | None = None
    provenance: Provenance = Provenance()


async def find_station(
    query: Annotated[
        str | None,
        Field(default=None, description="Station name or EBAS code, in any spelling: 'Hyytiala' finds 'Hyytiälä'."),
    ] = None,
    stations: StationsFilter = None,
    country: CountryFilter = None,
    network: NetworkFilter = None,
    has_data_for: Annotated[
        VariableKey | None,
        Field(default=None, description="Keep only stations holding a usable mean for this variable in some year."),
    ] = None,
    limit: Annotated[int, Field(default=20, ge=1, le=100)] = 20,
) -> FindStationResult:
    """Resolve a station name or code, or browse the catalogue by filters.

    Start here: station codes like FI0050R are what every other tool takes, and no
    one types them from memory. A blank query with filters is a browse; a query with
    filters is a search within them.

    Matching is on text — code and name, case- and accent-insensitive. It cannot
    interpret a description like "Finnish forest site"; for those, filter by country
    and read the candidates, or load the actris://catalog/stations resource and
    choose from it. A query that matches nothing returns the closest candidates
    rather than an empty list, so narrow from what comes back.

    Coverage is reported across every year this server holds, not for one period.
    """
    catalog = await database.get_station_catalog()

    wanted = {s.upper() for s in stations} if stations else None
    candidates = [
        row
        for row in catalog
        if (wanted is None or row["id"].upper() in wanted)
        and _matches_filters(country, network, row["country"], row["networks"])
        and (has_data_for is None or row["years"].get(has_data_for))
    ]

    note: str | None = None
    hint: str | None = None

    facilities = (await actris_md.get_facilities())["facilities"]

    def to_match(row: dict, how: str) -> StationMatch:
        facility = facilities.get(row["id"]) or {}
        return StationMatch(
            id=row["id"],
            name=row["name"],
            country=row["country"],
            lat=round(row["lat"], 4),
            lon=round(row["lon"], 4),
            networks=[n for n in row["networks"].split(",") if n],
            coverage={var: compress_years(years) for var, years in sorted(row["years"].items())},
            matched_on=how,
            altitude_m=facility.get("altitude_m"),
            actris_labelling=facility.get("labelling_status"),
            actris_active=facility.get("active"),
            actris_url=facility.get("uri"),
        )

    if query:
        needle = fold(query)
        scored: list[tuple[int, str, dict, str]] = []
        for row in candidates:
            code, name = row["id"].casefold(), fold(row["name"])
            if code == needle:
                scored.append((100, name, row, "code"))
            elif code.startswith(needle):
                scored.append((90, name, row, "code"))
            elif name == needle:
                scored.append((80, name, row, "name"))
            elif name.startswith(needle):
                scored.append((70, name, row, "name"))
            elif needle in name:
                scored.append((60, name, row, "name"))
        scored.sort(key=lambda s: (-s[0], s[1]))
        matches = [to_match(row, how) for _, _, row, how in scored]

        if not matches:
            # Never answer a non-empty query with an empty list: "no matches" reads
            # as "no such station" and ends the session, while candidates read as
            # "narrow this down" and continue it.
            close = difflib.get_close_matches(
                needle, [fold(r["name"]) for r in candidates], n=limit, cutoff=0.4
            )
            by_name = {fold(r["name"]): r for r in candidates}
            matches = [to_match(by_name[name], "approximate") for name in close if name in by_name]
            if matches:
                note = (
                    f"Nothing matched '{query}' exactly; these are the closest station "
                    "names. Check before using one."
                )
            else:
                matches = [to_match(row, "filter") for row in candidates[:limit]]
                countries = sorted({row["country"] for row in candidates})
                note = (
                    f"Nothing matched '{query}'. This server only matches station names "
                    "and codes, not descriptions."
                )
                hint = (
                    "Filter by country and read the candidates: "
                    + ", ".join(countries[:25])
                    + ("…" if len(countries) > 25 else "")
                )
    else:
        matches = [to_match(row, "filter") for row in candidates]

    n_matched = len(matches)
    kept = matches[:limit]
    truncated = n_matched > limit
    if truncated and not hint:
        hint = "Narrow by country, network or has_data_for, or raise limit (max 100)."

    if not kept and not query:
        note = (
            "No station matches those filters. Drop one of them, or call get_coverage "
            "to see what this server holds."
        )

    empty_coverage = [m.id for m in kept if not m.coverage]
    if empty_coverage:
        existing = note + " " if note else ""
        note = (
            f"{existing}In the record but holding no usable value for any variable: "
            f"{', '.join(empty_coverage)}."
        )

    return FindStationResult(
        matches=kept,
        n_matched=n_matched,
        truncated=truncated,
        n_remaining=max(0, n_matched - limit),
        hint=hint,
        note=note,
    )


# ── get_series ────────────────────────────────────────────────────────────────

class SeriesRow(BaseModel):
    station_id: str
    station_name: str
    variable: str
    unit: str
    period_start: str
    period_end: str
    resolution: Resolution = "annual"
    mean: float | None = Field(
        description="Null means the period was requested and no usable value exists — not that it was omitted."
    )


class SeriesResult(BaseModel):
    rows: list[SeriesRow]
    period_start: str
    period_end: str
    resolution: Resolution = "annual"
    n_stations_requested: int = 0
    n_stations_returned: int = 0
    truncated: bool = False
    n_remaining: int = 0
    hint: str | None = None
    note: str | None = None
    error: str | None = None
    provenance: Provenance = Provenance()


async def get_series(
    stations: Annotated[
        list[str],
        Field(description="EBAS station codes. Required — resolve names with find_station first."),
    ],
    variables: Annotated[
        list[VariableKey] | None,
        Field(default=None, description="Defaults to all three."),
    ] = None,
    start: Annotated[
        str | None,
        Field(default=None, description="ISO date or year, e.g. '2005' or '2005-01-01'. Defaults to the earliest period holding data."),
    ] = None,
    end: Annotated[
        str | None,
        Field(default=None, description="ISO date or year. Defaults to the latest period holding data — which is not the current year."),
    ] = None,
    resolution: Annotated[Resolution, Field(default="annual")] = "annual",
) -> SeriesResult:
    """Annual means for named stations over a period range.

    The workhorse: one row per station, variable and period. Every period in the
    range is present, with a null mean where no usable value exists — a period
    absent from the rows would be indistinguishable from one that was never asked
    for.

    Capped at 10 stations and 30 periods, and truncation drops whole stations: a
    station returned with only part of its record reads as complete and invites a
    trend that is not there. For questions across many stations use get_ranking or
    get_change instead.

    Omitting start or end resolves to the range that actually holds data, which is
    not the current year — Level 2 publication lags by a year or two.
    """
    wanted_variables = list(variables) if variables else list(VARIABLES)

    available: set[int] = set()
    for variable in wanted_variables:
        available.update(await _periods_with_data(variable))

    if not available:
        return SeriesResult(
            rows=[], period_start="", period_end="", error="no_data",
            note="This server holds no data for the requested variables at all.",
        )

    year_from = _year_of(start) if start else min(available)
    year_to = _year_of(end) if end else max(available)
    if year_from > year_to:
        year_from, year_to = year_to, year_from

    note: str | None = None
    if start is None or end is None:
        note = (
            f"Range defaulted to {year_from}–{year_to}, the periods that hold data. "
            "The current year is normally empty: Level 2 publication lags."
        )

    years = list(range(year_from, year_to + 1))
    if len(years) > MAX_SERIES_PERIODS:
        years = years[-MAX_SERIES_PERIODS:]
        note = ((note + " ") if note else "") + (
            f"Period range trimmed to the most recent {MAX_SERIES_PERIODS}: "
            f"{years[0]}–{years[-1]}."
        )

    requested = list(dict.fromkeys(s.upper() for s in stations))
    stored = await database.get_series_rows(requested, wanted_variables, years[0], years[-1])

    by_key: dict[tuple[str, str, int], float | None] = {}
    names: dict[str, str] = {}
    for row in stored:
        by_key[(row["station_id"], row["variable"], row["year"])] = row["mean"]
        names.setdefault(row["station_id"], row["name"])

    groups: list[tuple[str, list[SeriesRow]]] = []
    for station_id in requested:
        rows: list[SeriesRow] = []
        for variable in wanted_variables:
            unit = VARIABLES[variable].unit
            for year in years:
                start_iso, end_iso = annual_period(year)
                mean = by_key.get((station_id, variable, year))
                rows.append(
                    SeriesRow(
                        station_id=station_id,
                        station_name=names.get(station_id, station_id),
                        variable=variable,
                        unit=unit,
                        period_start=start_iso,
                        period_end=end_iso,
                        mean=mean if has_value(mean) else None,
                    )
                )
        groups.append((station_id, rows))

    kept, remaining = cap_groups(groups, MAX_SERIES_ROWS, MAX_SERIES_STATIONS)

    unknown = [s for s in requested if s not in names]
    if unknown:
        note = ((note + " ") if note else "") + (
            f"No record at all for: {', '.join(unknown)}. Their rows are all null. "
            "Check the codes with find_station."
        )

    return SeriesResult(
        rows=kept,
        period_start=annual_period(years[0])[0],
        period_end=annual_period(years[-1])[1],
        n_stations_requested=len(requested),
        n_stations_returned=len(requested) - remaining,
        truncated=remaining > 0,
        n_remaining=remaining,
        hint=(
            "Result capped by whole stations. Ask for fewer stations, or use "
            "get_ranking / get_change for questions spanning many of them."
            if remaining
            else None
        ),
        note=note,
    )


# ── The aggregate three ───────────────────────────────────────────────────────
#
# Built together so `n_stations` means one thing across all of them, and so all
# three tell "no data" apart from a genuine zero. They read station_records and
# apply the same has_value rule as the dashboard, rather than the precomputed
# network_stats rows, so a filtered question and an unfiltered one are answered
# the same way.

class RankingRow(BaseModel):
    rank: int
    station_id: str
    name: str
    country: str
    networks: list[str]
    mean: float


class RankingResult(BaseModel):
    variable: str
    unit: str
    period_start: str
    period_end: str
    resolution: Resolution = "annual"
    rows: list[RankingRow] = []
    n_with_data: int = 0
    n_considered: int = Field(default=0, description="Stations matching the filters, including those with no usable value.")
    truncated: bool = False
    n_remaining: int = 0
    hint: str | None = None
    note: str | None = None
    error: str | None = None
    available_periods: str | None = None
    suggestion: str | None = None
    provenance: Provenance = Provenance()


async def get_ranking(
    period: Annotated[str, Field(description="ISO date or year, e.g. '2020'.")],
    variable: VariableKey,
    stations: StationsFilter = None,
    country: CountryFilter = None,
    network: NetworkFilter = None,
    limit: Annotated[int, Field(default=25, ge=1, le=200)] = 25,
) -> RankingResult:
    """Stations ranked highest to lowest for one period and variable.

    The ranking chart as data. Use this instead of get_series when the question is
    about many stations at one time rather than one station over time.

    Stations matching the filters but holding no usable value for the period are
    counted in n_considered and left out of the rows — the gap between the two
    numbers is how much of the network was silent that year.
    """
    year = _year_of(period)
    unit = VARIABLES[variable].unit
    start_iso, end_iso = annual_period(year)

    records = await database.get_station_records(year, variable)
    if not records:
        problem = _no_data(variable, year, await _periods_with_data(variable))
        return RankingResult(
            variable=variable, unit=unit, period_start=start_iso, period_end=end_iso,
            error=problem["error"], note=problem["message"],
            available_periods=problem["available_periods"], suggestion=problem["suggestion"],
        )

    wanted = {s.upper() for s in stations} if stations else None
    considered = [
        r for r in records
        if (wanted is None or r["id"].upper() in wanted)
        and _matches_filters(country, network, r["country"], r["networks"])
    ]
    with_data = sorted(
        (r for r in considered if has_value(r["mean"])),
        key=lambda r: r["mean"],
        reverse=True,
    )

    rows = [
        RankingRow(
            rank=index,
            station_id=r["id"],
            name=r["name"],
            country=r["country"],
            networks=[n for n in r["networks"].split(",") if n],
            mean=round(r["mean"], 3),
        )
        for index, r in enumerate(with_data[:limit], start=1)
    ]

    note = None
    if considered and not with_data:
        note = (
            f"{len(considered)} station(s) match the filters for {year}, but none holds "
            "a usable value for that period."
        )
    elif not considered:
        note = "No station matches those filters for this period."

    return RankingResult(
        variable=variable, unit=unit, period_start=start_iso, period_end=end_iso,
        rows=rows,
        n_with_data=len(with_data),
        n_considered=len(considered),
        truncated=len(with_data) > limit,
        n_remaining=max(0, len(with_data) - limit),
        hint="Raise limit (max 200) or narrow by country or network." if len(with_data) > limit else None,
        note=note,
    )


class PeriodStats(BaseModel):
    period_start: str
    period_end: str
    resolution: Resolution = "annual"
    median: float | None = None
    q1: float | None = None
    q3: float | None = None
    min: float | None = None
    max: float | None = None
    n_stations: int = Field(default=0, description="Stations with a usable value in this period, after filters.")


class NetworkStatsResult(BaseModel):
    variable: str
    unit: str
    periods: list[PeriodStats] = []
    note: str | None = None
    error: str | None = None
    available_periods: str | None = None
    suggestion: str | None = None
    provenance: Provenance = Provenance()


async def get_network_stats(
    variable: VariableKey,
    start: Annotated[str | None, Field(default=None, description="ISO date or year. Defaults to the earliest period with data.")] = None,
    end: Annotated[str | None, Field(default=None, description="ISO date or year. Defaults to the latest period with data.")] = None,
    stations: StationsFilter = None,
    country: CountryFilter = None,
    network: NetworkFilter = None,
) -> NetworkStatsResult:
    """Distribution across stations — median, quartiles, range — per period.

    Answers "what is normal" rather than "what is this station". Computed from the
    same station values the ranking uses, so a filtered subset and the whole network
    are described the same way.

    n_stations counts stations holding a usable value, not stations that reported,
    and it moves year to year: treat a change in the median between two periods with
    different n_stations as partly a change in who was measuring.
    """
    unit = VARIABLES[variable].unit
    available = await _periods_with_data(variable)
    if not available:
        return NetworkStatsResult(
            variable=variable, unit=unit, error="no_data",
            note=f"This server holds no usable data for {variable}.",
        )

    year_from = _year_of(start) if start else min(available)
    year_to = _year_of(end) if end else max(available)
    if year_from > year_to:
        year_from, year_to = year_to, year_from

    note = None
    if start is None or end is None:
        note = f"Range defaulted to {year_from}–{year_to}, the periods holding data."

    wanted = {s.upper() for s in stations} if stations else None
    periods: list[PeriodStats] = []
    for year in range(year_from, year_to + 1):
        records = await database.get_station_records(year, variable)
        selected = [
            r for r in records
            if (wanted is None or r["id"].upper() in wanted)
            and _matches_filters(country, network, r["country"], r["networks"])
            and has_value(r["mean"])
        ]
        stats = compute_network_stats(selected, year, variable)
        start_iso, end_iso = annual_period(year)
        periods.append(
            PeriodStats(
                period_start=start_iso, period_end=end_iso,
                median=stats["median"], q1=stats["q1"], q3=stats["q3"],
                min=stats["min"], max=stats["max"], n_stations=stats["n_stations"],
            )
        )

    return NetworkStatsResult(variable=variable, unit=unit, periods=periods, note=note)


class ChangeRow(BaseModel):
    station_id: str
    name: str
    country: str
    from_mean: float | None = None
    to_mean: float | None = None
    change_abs: float | None = None
    change_pct: float | None = None
    status: str = Field(
        description="changed, or missing_from / missing_to / missing_both when one or both periods hold no usable value."
    )


class ChangeResult(BaseModel):
    variable: str
    unit: str
    from_period_start: str
    from_period_end: str
    to_period_start: str
    to_period_end: str
    resolution: Resolution = "annual"
    rows: list[ChangeRow] = []
    n_changed: int = 0
    n_incomplete: int = Field(default=0, description="Stations reported with a status other than 'changed'.")
    truncated: bool = False
    n_remaining: int = 0
    hint: str | None = None
    note: str | None = None
    error: str | None = None
    provenance: Provenance = Provenance()


async def get_change(
    variable: VariableKey,
    from_period: Annotated[str, Field(description="ISO date or year, e.g. '2005'.")],
    to_period: Annotated[str, Field(description="ISO date or year, e.g. '2020'.")],
    stations: StationsFilter = None,
    country: CountryFilter = None,
    network: NetworkFilter = None,
    limit: Annotated[int, Field(default=25, ge=1, le=200)] = 25,
) -> ChangeResult:
    """Change between two periods per station, largest decline first.

    Its own tool because the arithmetic across ~144 stations is where doing it by
    hand goes wrong. Sorted by percentage change ascending, so the steepest declines
    lead.

    Stations measured in only one of the two periods are reported with a status
    rather than dropped: a station that stopped reporting is not a station that fell
    to zero, and the difference changes what the answer means.
    """
    year_from, year_to = _year_of(from_period), _year_of(to_period)
    unit = VARIABLES[variable].unit
    from_start, from_end = annual_period(year_from)
    to_start, to_end = annual_period(year_to)

    first = await database.get_station_records(year_from, variable)
    second = await database.get_station_records(year_to, variable)
    if not first and not second:
        problem = _no_data(variable, year_from, await _periods_with_data(variable))
        return ChangeResult(
            variable=variable, unit=unit,
            from_period_start=from_start, from_period_end=from_end,
            to_period_start=to_start, to_period_end=to_end,
            error=problem["error"],
            note=f"{problem['message']} {problem['suggestion']}",
        )

    wanted = {s.upper() for s in stations} if stations else None

    def keep(record: dict) -> bool:
        return (wanted is None or record["id"].upper() in wanted) and _matches_filters(
            country, network, record["country"], record["networks"]
        )

    from_map = {r["id"]: r for r in first if keep(r)}
    to_map = {r["id"]: r for r in second if keep(r)}

    rows: list[ChangeRow] = []
    for station_id in sorted(set(from_map) | set(to_map)):
        before = from_map.get(station_id)
        after = to_map.get(station_id)
        source = before or after
        assert source is not None
        before_mean = before["mean"] if before and has_value(before["mean"]) else None
        after_mean = after["mean"] if after and has_value(after["mean"]) else None

        if before_mean is not None and after_mean is not None:
            status, change_abs = "changed", after_mean - before_mean
            change_pct = round(change_abs / before_mean * 100, 2)
        else:
            change_abs = change_pct = None
            status = (
                "missing_both" if before_mean is None and after_mean is None
                else "missing_from" if before_mean is None
                else "missing_to"
            )

        rows.append(
            ChangeRow(
                station_id=station_id, name=source["name"], country=source["country"],
                from_mean=round(before_mean, 3) if before_mean is not None else None,
                to_mean=round(after_mean, 3) if after_mean is not None else None,
                change_abs=round(change_abs, 3) if change_abs is not None else None,
                change_pct=change_pct, status=status,
            )
        )

    changed = sorted([r for r in rows if r.status == "changed"], key=lambda r: r.change_pct or 0)
    incomplete = [r for r in rows if r.status != "changed"]
    kept = changed[:limit]

    return ChangeResult(
        variable=variable, unit=unit,
        from_period_start=from_start, from_period_end=from_end,
        to_period_start=to_start, to_period_end=to_end,
        # Incomplete stations always travel with the result: they are the ones an
        # unqualified "declined most" answer would quietly omit.
        rows=kept + incomplete,
        n_changed=len(changed),
        n_incomplete=len(incomplete),
        truncated=len(changed) > limit,
        n_remaining=max(0, len(changed) - limit),
        hint="Raise limit (max 200) or narrow by country or network." if len(changed) > limit else None,
        note=(
            f"{len(incomplete)} station(s) lack a usable value in one or both periods; "
            "they carry a status instead of a change."
            if incomplete else None
        ),
    )
