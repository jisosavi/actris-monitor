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

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import ebas_thredds as et  # noqa: E402
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


def test_year_indices_report_where_the_slice_starts() -> None:
    """The hour offset is what lets several files share one calendar."""
    fi = _FileInfo(
        name="x.nc", station="FI0050R", instrument="cpc",
        start=date(2023, 1, 1), end=date(2024, 1, 1),
    )
    idx0, idx1, offset = et._estimate_year_indices(fi, 2023)
    assert (idx0, offset) == (0, 0)
    assert idx1 == HOURS_2023 - 1

    mid = _FileInfo(
        name="y.nc", station="FI0050R", instrument="cpc",
        start=date(2023, 7, 1), end=date(2024, 1, 1),
    )
    _, _, mid_offset = et._estimate_year_indices(mid, 2023)
    assert mid_offset == (date(2023, 7, 1) - date(2023, 1, 1)).days * 24


@pytest.mark.anyio
async def test_sample_count_disagreeing_with_the_filename_yields_no_coverage(monkeypatch) -> None:
    """The mean survives; the coverage claim does not.

    `_estimate_year_indices` infers 24 samples a day from the filename and never
    reads the time array. That is tolerable for a mean and load-bearing for a
    fraction, so a file whose length contradicts the inference is excluded from
    coverage rather than guessed at.
    """
    async def fake_fetch(client, base_url, constraint):  # noqa: ANN001
        return "unused"

    # 24 values where the slice asked for 48 hours: not hourly.
    monkeypatch.setattr(et, "_fetch_opendap_ascii", fake_fetch)
    monkeypatch.setattr(et, "_parse_first_section_floats", lambda _text: np.full(24, 5.0))

    result = await et._compute_annual_mean(None, "http://x/file.nc", "var", 0, 47, 0.0, 0)
    assert result.mean == pytest.approx(5.0), "the mean is unchanged behaviour"
    assert result.valid_hours is None, "coverage must not be inferred from a wrong denominator"


@pytest.mark.anyio
async def test_matching_sample_count_maps_onto_the_year(monkeypatch) -> None:
    async def fake_fetch(client, base_url, constraint):  # noqa: ANN001
        return "unused"

    values = np.array([1.0, -999.0, 3.0, np.nan, 5.0])  # two invalid
    monkeypatch.setattr(et, "_fetch_opendap_ascii", fake_fetch)
    monkeypatch.setattr(et, "_parse_first_section_floats", lambda _text: values)

    result = await et._compute_annual_mean(None, "http://x/file.nc", "var", 0, 4, 0.0, 100)
    assert result.valid_hours is not None
    # Offset applied, invalid samples excluded.
    assert list(result.valid_hours) == [100, 102, 104]
    assert result.mean == pytest.approx(3.0)
