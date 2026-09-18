"""
Observed-fraction: the arithmetic that would be wrong quietly.

`observed_fraction` replaced a field that claimed to be a coverage fraction and
was a has-data flag. The ways a replacement goes wrong are all silent — a
plausible percentage is indistinguishable from a correct one by eye — so what is
tested here is:

- overlapping files are unioned, not summed, so nothing exceeds the year;
- a leap year divides by 8784;
- "could not determine" stays distinct from "observed nothing";
- a file whose sample count contradicts the filename is excluded from coverage
  while still contributing its mean.

No network and no database: these drive the pure pieces directly.
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import asyncio
import json

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import ebas_thredds as et  # noqa: E402
from datetime import timedelta  # noqa: E402
from ebas_thredds import _FileInfo, _FileSample, union_observed_hours  # noqa: E402

HOURS_2023 = 8760
HOURS_2024 = 8784  # leap


def sample(hours: list[int] | None) -> _FileSample:
    return _FileSample(mean=1.0, valid_hours=None if hours is None else np.array(hours))


def test_overlapping_files_are_unioned_not_summed() -> None:
    """Two files covering the same hours must not read as twice the coverage."""
    same = list(range(0, 4380))  # the first half of the year, twice over
    out = union_observed_hours([("FI0050R", sample(same)), ("FI0050R", sample(same))], HOURS_2023)
    assert out["FI0050R"] == pytest.approx(0.5, abs=1e-3)


def test_complementary_files_add_up() -> None:
    """Files covering different halves should together cover the year."""
    first = list(range(0, 4380))
    second = list(range(4380, HOURS_2023))
    out = union_observed_hours([("X", sample(first)), ("X", sample(second))], HOURS_2023)
    assert out["X"] == pytest.approx(1.0, abs=1e-4)


def test_leap_year_divides_by_8784() -> None:
    full_non_leap = list(range(HOURS_2023))
    out = union_observed_hours([("X", sample(full_non_leap))], HOURS_2024)
    assert out["X"] < 1.0
    assert out["X"] == pytest.approx(HOURS_2023 / HOURS_2024, abs=1e-4)


def test_unconfirmed_sampling_is_absent_not_zero() -> None:
    """The distinction the whole rename exists for."""
    out = union_observed_hours([("X", sample(None))], HOURS_2023)
    assert "X" not in out, "a file with unconfirmable sampling must not imply 0.0"

    read_but_empty = union_observed_hours([("Y", sample([]))], HOURS_2023)
    assert read_but_empty["Y"] == 0.0


def test_hours_outside_the_year_are_dropped() -> None:
    """A filename-derived offset can overshoot; it must not index out of bounds."""
    out = union_observed_hours([("X", sample([0, 1, HOURS_2023 + 50, -3]))], HOURS_2023)
    # Stored to 4 decimals — 0.01% is finer than anything worth displaying.
    assert out["X"] == pytest.approx(round(2 / HOURS_2023, 4))


def _axis(times_days, epoch=date(1900, 1, 1), stride=24):
    """A _TimeAxis over an explicit list of timestamps, as the file would report."""
    arr = np.asarray(times_days, dtype=float)
    return et._TimeAxis(
        n=arr.size, stride=stride, coarse=arr[::stride], epoch=epoch, unit_days=1.0
    )


def _days(d: date, epoch: date = date(1900, 1, 1)) -> float:
    return float((d - epoch).days)


def _hourly(first: date, hours: int, epoch: date = date(1900, 1, 1)):
    return [_days(first, epoch) + h / 24 for h in range(hours)]


def _patch_fetch(monkeypatch, times, values):
    """Serve `time[...]` and the data variable from in-memory arrays."""
    import json

    async def fake_fetch(client, base_url, constraint):  # noqa: ANN001
        inside = constraint[constraint.index("[") + 1 : constraint.rindex("]")]
        lo, hi = (int(x) for x in inside.split(":")[-2:])
        src = times if constraint.startswith("time[") else values
        return json.dumps(list(src[lo : hi + 1]))

    monkeypatch.setattr(et, "_fetch_opendap_ascii", fake_fetch)
    monkeypatch.setattr(
        et, "_parse_first_section_floats", lambda t: np.array(json.loads(t), dtype=float)
    )


def test_bracket_covers_the_year_and_nothing_beyond_the_array() -> None:
    times = _hourly(date(2003, 1, 1), 24 * 400)
    axis = _axis(times)

    lo, hi = axis.bracket(date(2003, 1, 1), date(2004, 1, 1))
    assert lo == 0
    assert hi <= axis.n - 1, "a bracket must never point past the array"

    # Years the file does not reach, on either side. Before the fix a year
    # *earlier* than the file returned a small range at index 0 instead of None,
    # which cost a wasted request for every non-covering file.
    assert axis.bracket(date(2010, 1, 1), date(2011, 1, 1)) is None
    assert axis.bracket(date(1998, 1, 1), date(1999, 1, 1)) is None


def test_a_year_with_fewer_samples_than_one_stride_is_still_found() -> None:
    """Equal searchsorted bounds do not mean absent — sparse years have data."""
    times = _hourly(date(2003, 1, 1), 24 * 300) + _hourly(date(2005, 6, 1), 3)
    axis = _axis(times, stride=100)
    assert axis.bracket(date(2005, 1, 1), date(2006, 1, 1)) is not None


@pytest.mark.anyio
async def test_a_gap_does_not_shift_the_year(monkeypatch) -> None:
    """The bug this whole change exists for.

    A file that starts in 2000, stops, and resumes in 2002. Index arithmetic put
    2002's window a year early and reported 2001's numbers under 2002. Cutting the
    window by the file's own timestamps cannot do that.
    """
    early = _hourly(date(2000, 1, 1), 24 * 10)      # value 1.0
    late = _hourly(date(2002, 1, 1), 24 * 10)       # value 9.0
    times = early + late
    values = [1.0] * len(early) + [9.0] * len(late)
    _patch_fetch(monkeypatch, times, values)

    fi = _FileInfo(
        name="x.nc", station="FI0050R", instrument="cpc",
        start=date(2000, 1, 1), end=date(2003, 1, 1), revision=date(2020, 1, 1),
    )
    sem = asyncio.Semaphore(4)

    got_2002 = await et._fetch_file_mean(None, fi, "v", 2002, 0.0, sem, _axis(times))
    assert got_2002.mean == pytest.approx(9.0), "2002 must read 2002's values"

    got_2000 = await et._fetch_file_mean(None, fi, "v", 2000, 0.0, sem, _axis(times))
    assert got_2000.mean == pytest.approx(1.0)

    got_2001 = await et._fetch_file_mean(None, fi, "v", 2001, 0.0, sem, _axis(times))
    assert got_2001.mean is None, "a year inside the gap holds nothing"


@pytest.mark.anyio
async def test_hours_come_from_timestamps_not_positions(monkeypatch) -> None:
    """Coverage must fall when a file has a hole, not slide along with it."""
    times = _hourly(date(2005, 1, 1), 24) + _hourly(date(2005, 6, 1), 24)
    values = [2.0] * 48
    _patch_fetch(monkeypatch, times, values)

    fi = _FileInfo(
        name="y.nc", station="X", instrument="cpc",
        start=date(2005, 1, 1), end=date(2006, 1, 1), revision=date(2020, 1, 1),
    )
    out = await et._fetch_file_mean(None, fi, "v", 2005, 0.0, asyncio.Semaphore(2), _axis(times))

    assert out.valid_hours is not None
    assert len(out.valid_hours) == 48
    # 1 January and 1 June, not 48 consecutive hours from the file's start.
    assert out.valid_hours[0] == 0
    assert out.valid_hours[24] == (date(2005, 6, 1) - date(2005, 1, 1)).days * 24


@pytest.mark.anyio
async def test_a_failed_fetch_is_logged_not_swallowed(monkeypatch, caplog) -> None:
    """The silence was the reason this went unnoticed for months."""
    async def boom(client, base_url, constraint):  # noqa: ANN001
        raise RuntimeError("Invalid Parameter Exception: DArray")

    monkeypatch.setattr(et, "_fetch_opendap_ascii", boom)
    fi = _FileInfo(
        name="z.nc", station="X", instrument="cpc",
        start=date(2000, 1, 1), end=date(2001, 1, 1), revision=date(2020, 1, 1),
    )
    axis = _axis(_hourly(date(2000, 1, 1), 48))

    with caplog.at_level("WARNING"):
        out = await et._fetch_file_mean(None, fi, "v", 2000, 0.0, asyncio.Semaphore(2), axis)

    assert out.mean is None
    assert any("z.nc" in r.getMessage() for r in caplog.records), (
        "the failure must name the file"
    )


def test_duration_field_is_the_extent_not_the_revision_date() -> None:
    """parts[2] is when the file was revised; parts[6] is how much data it holds."""
    assert et._parse_duration("7y") == timedelta(days=7 * 365.25)
    assert et._parse_duration("3mo") == timedelta(days=3 * 30.44)
    assert et._parse_duration("10w") == timedelta(days=70)
    assert et._parse_duration("banana") is None

    name = ("FI0096G.20000202120000.20181031145000.nephelometer..aerosol.7y.1h."
            "a.b.lev2.nc")
    xml = ('<catalog xmlns="http://www.unidata.ucar.edu/namespaces/thredds/InvCatalog/v1.0">'
           f'<dataset name="{name}"/></catalog>')
    fi = et._parse_catalog(xml)[0]

    assert fi.start == date(2000, 2, 2)
    assert fi.revision == date(2018, 10, 31), "parts[2] kept under its real name"
    assert fi.end.year == 2007, "extent comes from 7y, not from the 2018 revision"
