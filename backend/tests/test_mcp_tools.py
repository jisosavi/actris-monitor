"""
Tool behaviour, exercised through a real MCP client.

`Client(mcp)` connects straight to the server object — no HTTP, no port, no
database server — so these run anywhere `pytest` does, in about a second.

What is worth testing here is not that the SQL works. It is the conventions that
fail *silently* when they regress: an absent period must come back as an explicit
null rather than a missing row, truncation must drop whole stations, a query that
matches nothing must still offer a way forward, and a station measured in only one
of two periods must not quietly vanish from a "declined most" answer. Each of those
has a failure mode where the tool returns a plausible result that means something
different from what it says.

Run:  cd backend && pytest
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import actris_md  # noqa: E402
import database  # noqa: E402
from mcp import Client  # noqa: E402
from mcp_server.server import mcp  # noqa: E402


@pytest.fixture
def anyio_backend():
    return "asyncio"


# A miniature network: two Finnish stations, one German, one that exists but never
# produced a usable value, and a deliberate gap year.
STATIONS = {
    "FI0050R": ("Hyytiälä", "FI", "ACTRIS,GAW-WDCA", 61.85, 24.29),
    "FI0096G": ("Pallas (Sammaltunturi)", "FI", "ACTRIS", 67.97, 24.12),
    "DE0043G": ("Neuglobsow", "DE", "EMEP", 53.14, 13.03),
    "BE0007R": ("Vielsalm", "BE", "ACTRIS", 50.30, 6.00),
}
MEANS = {
    ("FI0050R", 2018): 1000.0, ("FI0050R", 2019): 900.0, ("FI0050R", 2020): 500.0,
    ("FI0096G", 2018): 200.0, ("FI0096G", 2020): 260.0,   # 2019 missing entirely
    ("DE0043G", 2018): 400.0, ("DE0043G", 2019): 420.0, ("DE0043G", 2020): 440.0,
    ("BE0007R", 2018): None, ("BE0007R", 2019): None, ("BE0007R", 2020): None,
}


# Facility metadata, primed into the module cache so no test reaches the network.
# FI0050R is labelled and active; BE0007R is registered but not labelled; FI0096G
# has no facility record at all.
FACILITIES = {
    "FI0050R": {"identifier": "abc1", "name": "Hyytiälä", "country_code": "FI",
                "altitude_m": 181.0, "labelling_status": "labelled", "active": True,
                "uri": "https://data.actris.eu/facility/abc1"},
    "BE0007R": {"identifier": "def2", "name": "Vielsalm", "country_code": "BE",
                "altitude_m": 490.0, "labelling_status": "not labelled", "active": False,
                "uri": "https://data.actris.eu/facility/def2"},
}


@pytest.fixture
async def seeded(tmp_path, anyio_backend, monkeypatch):
    from datetime import datetime, timezone
    monkeypatch.setattr(actris_md, "_cache", (
        {"fetched_at": datetime.now(timezone.utc).isoformat(), "stale": False,
         "source": "test", "facilities": FACILITIES},
        datetime.now(timezone.utc),
    ))
    await database.init_db(str(tmp_path / "test.db"))
    for year in (2018, 2019, 2020):
        records = []
        for station_id, (name, country, networks, lat, lon) in STATIONS.items():
            if (station_id, year) not in MEANS:
                continue
            records.append({
                "id": station_id, "name": name, "lat": lat, "lon": lon,
                "country": country, "mean": MEANS[(station_id, year)],
                # Deliberately varied, and null for one station-year: the tools
                # must carry the value through and must not turn null into 0.
                "observed_fraction": None if year == 2019 else 0.75,
                "networks": networks,
            })
        await database.upsert_station_records(year, "N", records)
        usable = [r["mean"] for r in records if r["mean"]]
        await database.upsert_network_stats(year, "N", {
            "median": sorted(usable)[len(usable) // 2] if usable else None,
            "q1": None, "q3": None, "min": min(usable, default=None),
            "max": max(usable, default=None), "n_stations": len(usable),
        })
    yield
    await database.close_db()


async def call(name: str, args: dict) -> dict:
    async with Client(mcp) as client:
        result = await client.call_tool(name, args)
    assert result.is_error is False, f"{name} returned an error result"
    return result.structured_content


pytestmark = pytest.mark.anyio


# ── find_station ──────────────────────────────────────────────────────────────

async def test_find_station_by_code(seeded):
    out = await call("find_station", {"query": "FI0050R"})
    assert [m["id"] for m in out["matches"]] == ["FI0050R"]
    assert out["matches"][0]["matched_on"] == "code"


async def test_find_station_folds_diacritics(seeded):
    """Nobody types Hyytiälä from an agent prompt."""
    out = await call("find_station", {"query": "hyytiala"})
    assert [m["id"] for m in out["matches"]] == ["FI0050R"]


async def test_find_station_never_returns_empty_for_a_query(seeded):
    """A semantic query cannot match, but must still leave somewhere to go."""
    out = await call("find_station", {"query": "finnish forest site"})
    assert out["matches"], "an empty list reads as 'no such station' and ends the session"
    assert out["note"], "the fallback has to say the match is not exact"


async def test_find_station_filters_are_catalogue_wide(seeded):
    out = await call("find_station", {"country": "FI"})
    assert sorted(m["id"] for m in out["matches"]) == ["FI0050R", "FI0096G"]
    out = await call("find_station", {"network": "EMEP"})
    assert [m["id"] for m in out["matches"]] == ["DE0043G"]


async def test_find_station_flags_stations_holding_nothing(seeded):
    """Vielsalm is real; a tool that hides it makes a model deny it exists."""
    out = await call("find_station", {"query": "Vielsalm"})
    assert [m["id"] for m in out["matches"]] == ["BE0007R"]
    assert out["matches"][0]["coverage"] == {}
    assert "BE0007R" in (out["note"] or "")


async def test_find_station_has_data_for_excludes_the_empty_one(seeded):
    out = await call("find_station", {"has_data_for": "N"})
    assert "BE0007R" not in [m["id"] for m in out["matches"]]


async def test_find_station_carries_facility_metadata(seeded):
    out = await call("find_station", {"query": "FI0050R"})
    m = out["matches"][0]
    assert m["altitude_m"] == 181.0
    assert m["actris_labelling"] == "labelled"
    assert m["actris_active"] is True
    assert m["actris_url"].endswith("/abc1")


async def test_find_station_degrades_without_a_facility_record(seeded):
    """FI0096G has no ACTRIS facility; the station must still resolve."""
    out = await call("find_station", {"query": "FI0096G"})
    m = out["matches"][0]
    assert m["id"] == "FI0096G"
    assert m["altitude_m"] is None and m["actris_labelling"] is None
    assert m["actris_active"] is None and m["actris_url"] is None


async def test_inactive_station_keeps_its_measurements(seeded):
    """`active` describes the registry, never the data. Vielsalm is inactive."""
    out = await call("find_station", {"query": "Vielsalm"})
    assert out["matches"][0]["actris_active"] is False
    series = await call("get_series", {"stations": ["BE0007R"], "variables": ["N"],
                                       "start": "2018", "end": "2018"})
    assert len(series["rows"]) == 1, "an inactive station is still queryable"


def test_duplicate_ebas_code_resolves_deterministically():
    """Two facilities share a code in the live data; the active one wins."""
    parsed = actris_md._parse([
        {"identifier": "zzz9", "name": "A", "active": False,
         "extra_metadata": {"insitu": {"ebas_station_code": "XX0001R"}}},
        {"identifier": "aaa1", "name": "B", "active": True,
         "extra_metadata": {"insitu": {"ebas_station_code": "XX0001R"}}},
    ])
    assert parsed["XX0001R"]["identifier"] == "aaa1"
    # With activity equal, the choice is still deterministic rather than arbitrary.
    tie = actris_md._parse([
        {"identifier": "zzz9", "active": False,
         "extra_metadata": {"insitu": {"ebas_station_code": "XX0002R"}}},
        {"identifier": "aaa1", "active": False,
         "extra_metadata": {"insitu": {"ebas_station_code": "XX0002R"}}},
    ])
    assert tie["XX0002R"]["identifier"] == "aaa1"


def test_only_unlabelled_is_excluded_from_the_actris_tag():
    """The six-value status collapses to a boolean at exactly one place."""
    assert actris_md.NOT_LABELLED == "not labelled"


# ── get_series ────────────────────────────────────────────────────────────────

async def test_get_series_emits_gaps_as_nulls(seeded):
    """FI0096G has no 2019 row at all; it must appear as an explicit null."""
    out = await call("get_series", {"stations": ["FI0096G"], "variables": ["N"],
                                    "start": "2018", "end": "2020"})
    years = {row["period_start"][:4]: row["mean"] for row in out["rows"]}
    assert years == {"2018": 200.0, "2019": None, "2020": 260.0}


async def test_get_series_defaults_to_periods_that_hold_data(seeded):
    out = await call("get_series", {"stations": ["FI0050R"]})
    assert out["period_start"].startswith("2018") and out["period_end"].startswith("2020")
    assert "2018" in (out["note"] or "")


async def test_get_series_truncates_by_whole_station(seeded, monkeypatch):
    """Half a station's periods reads as a complete record and invites a false trend."""
    import mcp_server.tools as tools_module
    monkeypatch.setattr(tools_module, "MAX_SERIES_STATIONS", 2)
    out = await call("get_series", {"stations": list(STATIONS), "variables": ["N"],
                                    "start": "2018", "end": "2020"})
    returned = {row["station_id"] for row in out["rows"]}
    assert len(returned) == 2 and out["truncated"] and out["n_remaining"] == 2
    per_station = {s: sum(1 for r in out["rows"] if r["station_id"] == s) for s in returned}
    assert set(per_station.values()) == {3}, "every returned station keeps all its periods"


async def test_get_series_says_when_a_code_is_unknown(seeded):
    out = await call("get_series", {"stations": ["NOPE99X"], "variables": ["N"],
                                    "start": "2018", "end": "2018"})
    assert all(row["mean"] is None for row in out["rows"])
    assert "NOPE99X" in (out["note"] or "")


# ── get_ranking ───────────────────────────────────────────────────────────────

async def test_get_ranking_orders_and_counts(seeded):
    out = await call("get_ranking", {"period": "2018", "variable": "N"})
    assert [r["station_id"] for r in out["rows"]] == ["FI0050R", "DE0043G", "FI0096G"]
    assert out["rows"][0]["rank"] == 1
    # Vielsalm is considered and excluded: the gap is the silent part of the network.
    assert out["n_with_data"] == 3 and out["n_considered"] == 4


async def test_get_ranking_teaches_on_an_empty_period(seeded):
    out = await call("get_ranking", {"period": "2031", "variable": "N"})
    assert out["error"] == "no_data"
    assert out["available_periods"] and out["suggestion"]


# ── get_network_stats ─────────────────────────────────────────────────────────

async def test_get_network_stats_counts_only_usable_values(seeded):
    out = await call("get_network_stats", {"variable": "N", "start": "2019", "end": "2019"})
    assert len(out["periods"]) == 1
    assert out["periods"][0]["n_stations"] == 2  # FI0050R and DE0043G; not the gap, not the empty one


async def test_get_network_stats_respects_filters(seeded):
    out = await call("get_network_stats", {"variable": "N", "country": "FI",
                                           "start": "2018", "end": "2018"})
    assert out["periods"][0]["n_stations"] == 2


# ── get_change ────────────────────────────────────────────────────────────────

async def test_get_change_ranks_steepest_decline_first(seeded):
    out = await call("get_change", {"variable": "N", "from_period": "2018", "to_period": "2020"})
    changed = [r for r in out["rows"] if r["status"] == "changed"]
    assert changed[0]["station_id"] == "FI0050R"      # -50%
    assert changed[0]["change_pct"] == pytest.approx(-50.0)


async def test_get_change_keeps_stations_missing_a_period(seeded):
    """A station that stopped reporting is not a station that fell to zero."""
    out = await call("get_change", {"variable": "N", "from_period": "2019", "to_period": "2020"})
    by_id = {r["station_id"]: r for r in out["rows"]}
    assert by_id["FI0096G"]["status"] == "missing_from"
    assert by_id["FI0096G"]["change_pct"] is None
    assert out["n_incomplete"] >= 1 and out["note"]


# ── conventions every tool shares ─────────────────────────────────────────────

@pytest.mark.parametrize(
    ("name", "args"),
    [
        ("get_coverage", {}),
        ("find_station", {"country": "FI"}),
        ("get_series", {"stations": ["FI0050R"]}),
        ("get_ranking", {"period": "2018", "variable": "N"}),
        ("get_network_stats", {"variable": "N"}),
        ("get_change", {"variable": "N", "from_period": "2018", "to_period": "2020"}),
    ],
)
async def test_every_tool_carries_provenance(seeded, name, args):
    """A model cites what it was handed; the caveats have to travel with the data."""
    out = await call(name, args)
    provenance = out["provenance"]
    assert "unweighted" in provenance["mean_method"]
    # The coverage sentence changed meaning when observed_fraction became a real
    # share of the period rather than a has-data flag. What has to survive is the
    # distinction a reader acts on: null is not zero.
    assert "observed_fraction" in provenance["coverage_basis"]
    assert "not the same as 0.0" in provenance["coverage_basis"]
    assert provenance["citation"]


# ── observed_fraction ─────────────────────────────────────────────────────────

@pytest.mark.anyio
async def test_series_carries_observed_fraction_including_the_null(seeded) -> None:
    """Null must survive as null.

    The field replaced one that conflated "could not determine" with "observed
    nothing". A layer that helpfully defaults it to 0 would reinstate exactly the
    confusion it was introduced to end, and nothing downstream could tell.
    """
    out = await call("get_series", {"stations": ["FI0050R"], "variables": ["N"],
                                    "start": "2018", "end": "2020"})
    by_year = {row["period_start"][:4]: row["observed_fraction"] for row in out["rows"]}

    assert by_year["2018"] == 0.75
    assert by_year["2020"] == 0.75
    assert by_year["2019"] is None, "a null coverage must not be rendered as 0"


@pytest.mark.anyio
async def test_ranking_carries_observed_fraction(seeded) -> None:
    """A ranking is where an unobserved year is most likely to mislead."""
    out = await call("get_ranking", {"period": "2018", "variable": "N"})
    assert out["rows"], "fixture should produce a ranking"
    assert all("observed_fraction" in row for row in out["rows"])
    assert out["rows"][0]["observed_fraction"] == 0.75
