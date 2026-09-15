"""
Resources: data the *application* loads and puts in front of the model, as opposed
to tools, which the model decides to call.

Same import discipline as `tools.py` — `database` and `variables` only, no FastAPI
and no MCP SDK. Registration lives in `server.py`.

Why the station catalog is a resource rather than only a tool: agents never say
`FI0050R`. Attached once, the catalog lets a model resolve "Hyytiälä" or answer
"which Finnish ACTRIS sites measure absorption" with no tool call at all, which
removes the failed-first-call that otherwise opens a session. `find_station` still
earns its place for clients that don't attach resources, for sessions where the
context is better spent elsewhere, and for fuzzy matching done server-side.
"""

from __future__ import annotations

from datetime import datetime, timezone

import actris_md
import database
from variables import VARIABLES

from .formatting import CITATION, MEAN_METHOD, SOURCE, compress_years


async def station_catalog() -> dict:
    """Every station this server holds data for, with which years it covers.

    Identity, position, network membership and a per-variable summary of which
    years hold a usable annual mean, as compact ranges ("2000-2019,2021-2024").
    Read this once instead of asking station-by-station.

    A snapshot, not a live view: clients cache resources, so treat `generated_at`
    as the age of what you are reading. It carries no measurements — use the tools
    for values.

    Roughly 50 KB for the full network. Worth attaching when a question involves
    picking stations; for a single lookup in a context-tight session, a station tool
    is the cheaper route.
    """
    rows = await database.get_station_catalog()
    facilities = (await actris_md.get_facilities())["facilities"]

    stations = []
    for row in rows:
        facility = facilities.get(row["id"]) or {}
        stations.append(
            {
                "id":       row["id"],
                "name":     row["name"],
                "country":  row["country"],
                # 4 dp is ~11 m, far finer than a station's footprint, and it stops
                # float repr (61.84740000000001) from padding a document whose whole
                # design constraint is size.
                "lat":      round(row["lat"], 4),
                "lon":      round(row["lon"], 4),
                "networks": [n for n in row["networks"].split(",") if n],
                "altitude_m": facility.get("altitude_m"),
                "actris_labelling": facility.get("labelling_status"),
                "actris_active": facility.get("active"),
                "actris_url": facility.get("uri"),
                "coverage": {
                    variable: compress_years(years)
                    for variable, years in sorted(row["years"].items())
                },
            }
        )

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "n_stations": len(stations),
        "variables": sorted(VARIABLES),
        "stations": stations,
        "notes": {
            "coverage": (
                "Years with a usable annual mean for that variable, as ranges. A year "
                "absent from a station's coverage was either never fetched or held no "
                "valid values — the two are indistinguishable here."
            ),
            "country": "Two-letter code from the EBAS station code prefix, not a country name.",
            "metadata": (
                "Name, position and networks are taken from the station's most recent "
                "year. Station metadata is stored per station-year and earlier years may "
                "differ."
            ),
            "actris_fields": (
                "altitude_m, actris_labelling, actris_active and actris_url come from the "
                "ACTRIS facility registry and describe the station NOW, not during any "
                "period below. actris_active is about registration, not measurement: an "
                "inactive station's historical values are valid, and some inactive "
                "stations still report. Null means no ACTRIS facility record."
            ),
            "mean_method": MEAN_METHOD,
            "source": SOURCE,
            "citation": CITATION,
        },
    }


def citation() -> str:
    """How to credit this data in a publication.

    The attribution EBAS/ACTRIS and the contributing station PIs expect, in a form
    you can paste into a manuscript.
    """
    return f"""\
# Citing ACTRIS / EBAS data

{SOURCE}.

## What to cite

{CITATION}

## Why the PIs matter

These measurements are made and quality-assured by the individual station
principal investigators, not by this dashboard. This project only reads the
published Level 2 files and aggregates them; the scientific credit belongs
upstream. Where a paper leans on a small number of stations, contact those
stations' PIs — both because it is expected practice and because they will know
things about their record that no metadata field carries.

## Data access

- EBAS: <https://ebas.nilu.no>
- ACTRIS Data Centre: <https://dc.actris.nilu.no>

The underlying files are Level 2 (fully quality-assured) netCDF, retrieved over
OPeNDAP from the NILU THREDDS server.

## What this aggregation does to the numbers

{MEAN_METHOD}

Coverage is recorded as presence only: this project knows whether a station-year
held any valid values, not what fraction of the year was observed. A station with
two months of winter data is indistinguishable from one with twelve months. If a
figure matters to a conclusion, go back to the source files.
"""
