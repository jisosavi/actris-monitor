"""
EBAS in-situ aerosol data via NILU THREDDS/OPeNDAP (ASCII endpoint).

Catalog:  https://thredds.nilu.no/thredds/catalog/ebas/catalog.xml
OPeNDAP:  https://thredds.nilu.no/thredds/dodsC/ebas/<filename>

Filename convention (dot-separated):
  STATION . START . END . INSTRUMENT . COMPONENT . MATRIX . DURATION . RESOLUTION . * . LEVEL . nc

Only lev2 files are used (fully QC'd data).

Data access strategy:
  1. Estimate year indices from filename dates (no time-array download needed)
  2. Fetch Wavelength coordinate (~100 bytes) when needed
  3. Fetch only the year's data slice (~130 KB per file)
  4. All results cached 24 h
"""

from __future__ import annotations

import asyncio
import logging
import re
import urllib.parse
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

import httpx
import numpy as np

import actris_md

from variables import VARIABLES

logger = logging.getLogger(__name__)

CATALOG_URL = "https://thredds.nilu.no/thredds/catalog/ebas/catalog.xml"
OPENDAP_BASE = "https://thredds.nilu.no/thredds/dodsC/ebas"

# Derived from variables.py so there is one definition, not two. The shapes below
# are what the rest of this module already expects: a list of instrument tokens per
# variable, and 0.0 standing for "no wavelength dimension" (see _compute_annual_mean).
INSTRUMENT_MAP: dict[str, list[str]] = {
    k: list(v.instruments) for k, v in VARIABLES.items()
}

NC_VAR: dict[str, str] = {k: v.nc_var for k, v in VARIABLES.items()}

TARGET_WAVELENGTH: dict[str, float] = {
    k: (v.wavelength_nm or 0.0) for k, v in VARIABLES.items()
}

_TTL = timedelta(hours=24)
_MAX_CONCURRENT = 20
_EPOCH = date(1900, 1, 1)


def _match_network(token: str) -> str | None:
    """Map a raw project token to a canonical network name, tolerating variations."""
    t = token.strip().upper()
    if t.startswith("ACTRIS"):
        return "ACTRIS"
    if t.startswith("EMEP"):
        return "EMEP"
    if "GAW" in t or "WDCA" in t:
        return "GAW-WDCA"
    return None


@dataclass
class _FileInfo:
    station: str
    name: str
    instrument: str
    start: date
    #: Last day the data covers, from the filename's duration field. Approximate —
    #: the duration is nominal and a file usually holds less. Use it to decide
    #: which files to *consider* for a year, never to compute an index.
    end: date
    #: When the file was last revised. This is `parts[2]`, which the first version
    #: of this parser mistook for the end date — see docs/year-slicing-plan.md.
    revision: date




class EbasThreddsClient:
    def __init__(self) -> None:
        self._http: httpx.AsyncClient | None = None
        self._catalog: tuple[list[_FileInfo], datetime] | None = None
        self._station_meta: dict[str, dict] = {}
        self._data_cache: dict[str, tuple[Any, datetime]] = {}
        # Time axes are per file, not per (file, year): a seven-year file serves
        # seven years from one read. None means the file has no usable time
        # coordinate and is not worth asking again.
        self._time_axes: dict[str, _TimeAxis | None] = {}
        self._actris_codes: set[str] | None = None

    async def start(self) -> None:
        self._http = httpx.AsyncClient(timeout=60.0)

    async def close(self) -> None:
        if self._http:
            await self._http.aclose()

    async def fetch_measurements(self, year: int, variable: str) -> list[dict]:
        """
        Return enriched station records for compute_annual_stats:
          [{id, name, lat, lon, country, mean, observed_fraction}, ...]

        `observed_fraction` is the share of the year's hours holding at least one
        usable value, unioned across the station's files rather than summed —
        files overlap in time and often carry different size cuts, so summing
        their counts would exceed the year. None where no file's sampling could be
        confirmed; 0.0 where files were read and held nothing.
        """
        key = f"{year}:{variable}"
        if (hit := self._get_cached(key)) is not None:
            return hit

        catalog = await self._get_catalog()

        instruments = INSTRUMENT_MAP[variable]
        nc_var = NC_VAR[variable]
        target_wl = TARGET_WAVELENGTH[variable]

        relevant = [
            f for f in catalog
            if f.instrument in instruments
            and f.start.year <= year <= f.end.year
        ]

        all_instrument = [f for f in catalog if f.instrument in instruments]

        rep_files: dict[str, _FileInfo] = {}
        for fi in all_instrument:
            if fi.station not in rep_files:
                rep_files[fi.station] = fi
        for fi in relevant:
            rep_files[fi.station] = fi

        sem = asyncio.Semaphore(_MAX_CONCURRENT)
        assert self._http

        # The time axis first: every window below is cut from it, so a file
        # without one contributes nothing rather than being sliced by guesswork.
        axes, metas = await asyncio.gather(
            asyncio.gather(*[self._get_time_axis(f, sem) for f in relevant]),
            asyncio.gather(*[self._get_station_meta(fi, sem) for fi in rep_files.values()]),
        )
        usable = [(f, ax) for f, ax in zip(relevant, axes) if ax is not None]
        if len(usable) < len(relevant):
            logger.info(
                "%d of %d %s files for %d have no usable time axis",
                len(relevant) - len(usable), len(relevant), variable, year,
            )

        samples = await asyncio.gather(*[
            _fetch_file_mean(self._http, f, nc_var, year, target_wl, sem, ax)
            for f, ax in usable
        ])
        relevant = [f for f, _ in usable]

        for fi, meta in zip(rep_files.values(), metas):
            if meta and fi.station not in self._station_meta:
                self._station_meta[fi.station] = meta

        # One hour slot per hour of the year — 8784 in a leap year. Unioned, not
        # counted, so two files covering the same fortnight do not read as a month.
        hours_in_year = (date(year + 1, 1, 1) - date(year, 1, 1)).days * 24

        by_station: dict[str, list[float]] = {}
        for fi, sample in zip(relevant, samples):
            if sample.mean is not None:
                by_station.setdefault(fi.station, []).append(sample.mean)

        observed = union_observed_hours(
            [(fi.station, sample) for fi, sample in zip(relevant, samples)],
            hours_in_year,
        )

        records = []
        for station_code, meta in self._station_meta.items():
            if station_code not in rep_files:
                continue
            values = by_station.get(station_code)
            records.append({
                "id":            station_code,
                "name":          meta["name"],
                "lat":           meta["lat"],
                "lon":           meta["lon"],
                "country":       meta["country"],
                "mean":          float(np.mean(values)) if values else None,
                # None, not 0.0: "we could not tell" and "nothing was measured"
                # are different claims and the panel shows them differently.
                "observed_fraction": observed.get(station_code),
                "networks":      meta.get("networks", ""),
            })

        self._set_cached(key, records)
        return records

    async def _get_actris_codes(self) -> set[str]:
        """EBAS station codes of facilities in the ACTRIS labelling process.

        Joins on the station code via the ACTRIS metadata API v3. The superseded
        dc.actris.nilu.no list forced a match on lowercased station name, which
        dropped any station whose spelling differed and said nothing about it.
        """
        if self._actris_codes is None:
            self._actris_codes = await actris_md.actris_labelled_codes()
            logger.info("ACTRIS labelling covers %d EBAS station codes", len(self._actris_codes))
        return self._actris_codes

    async def backfill_networks(self, station_ids: list[str]) -> dict[str, dict]:
        """
        Re-fetch .das metadata for all given station_ids.
        Returns {station_id: {lat, lon, networks}} for every station found in catalog.

        Picks one file per unique instrument type per station (max 5) so that
        measurements submitted under different frameworks (EMEP, GAW-WDCA, ACTRIS)
        are all captured — each submission can have a different 'project' value.
        Networks from all files are merged via set union.
        """
        catalog = await self._get_catalog()
        actris_codes = await self._get_actris_codes()

        station_ids_set = set(station_ids)
        station_files: dict[str, list[_FileInfo]] = {}
        for fi in catalog:
            if fi.station not in station_ids_set:
                continue
            files = station_files.setdefault(fi.station, [])
            # One file per instrument keeps request count low while covering
            # all frameworks (each instrument submission may use a different one).
            if len(files) < 5 and fi.instrument not in {f.instrument for f in files}:
                files.append(fi)

        if not station_files:
            return {}

        sem = asyncio.Semaphore(_MAX_CONCURRENT)
        assert self._http
        client = self._http

        async def _fetch_file(fi: _FileInfo) -> tuple[str, dict | None]:
            async with sem:
                return fi.station, await _fetch_station_meta_from_das(client, fi, actris_codes)

        all_results = await asyncio.gather(*[
            _fetch_file(fi)
            for files in station_files.values()
            for fi in files
        ])

        # First successful result per station provides name/lat/lon/country;
        # subsequent results from the same station only contribute their networks.
        merged: dict[str, dict] = {}
        for station_id, meta in all_results:
            if meta is None:
                continue
            if station_id not in merged:
                merged[station_id] = {**meta}
            else:
                existing = {n for n in merged[station_id]["networks"].split(",") if n}
                new_nets = {n for n in meta["networks"].split(",") if n}
                combined = sorted(existing | new_nets)
                merged[station_id]["networks"] = ",".join(combined)

        return merged

    async def get_catalog_years(self, variable: str) -> set[int]:
        """Return all years that have data for a given variable in the catalog."""
        catalog = await self._get_catalog()
        instruments = INSTRUMENT_MAP.get(variable, [])
        return {f.end.year for f in catalog if f.instrument in instruments}

    async def _get_catalog(self) -> list[_FileInfo]:
        if self._catalog:
            files, ts = self._catalog
            if datetime.now() - ts < _TTL:
                return files
        assert self._http
        resp = await self._http.get(CATALOG_URL)
        resp.raise_for_status()
        files = _parse_catalog(resp.text)
        self._catalog = (files, datetime.now())
        return files

    async def _get_time_axis(self, fi: _FileInfo, sem: asyncio.Semaphore) -> _TimeAxis | None:
        if fi.name in self._time_axes:
            return self._time_axes[fi.name]
        async with sem:
            assert self._http
            axis = await _fetch_time_axis(self._http, f"{OPENDAP_BASE}/{fi.name}", fi.name)
        self._time_axes[fi.name] = axis
        return axis

    async def _get_station_meta(self, fi: _FileInfo, sem: asyncio.Semaphore) -> dict | None:
        if fi.station in self._station_meta:
            return self._station_meta[fi.station]
        async with sem:
            assert self._http
            return await _fetch_station_meta_from_das(self._http, fi, self._actris_codes or set())

    def _get_cached(self, key: str) -> Any | None:
        if key in self._data_cache:
            data, ts = self._data_cache[key]
            if datetime.now() - ts < _TTL:
                return data
        return None

    def _set_cached(self, key: str, data: Any) -> None:
        self._data_cache[key] = (data, datetime.now())


# ── Catalog parsing ───────────────────────────────────────────────────────────

_DURATION_RE = re.compile(r"^(\d+)(mn|h|d|w|mo|y)$")

#: Nominal lengths. Months and years are approximate on purpose: this only has to
#: be good enough to decide which files a year could plausibly fall in, and the
#: true extent is read from the file's own time coordinate later.
_DURATION_DAYS: dict[str, float] = {
    "mn": 1 / 1440, "h": 1 / 24, "d": 1, "w": 7, "mo": 30.44, "y": 365.25,
}


def _parse_duration(token: str) -> timedelta | None:
    """`7y`, `3mo`, `10w`, `1h` → a duration. None when the field is not one."""
    m = _DURATION_RE.match(token)
    if not m:
        return None
    return timedelta(days=int(m.group(1)) * _DURATION_DAYS[m.group(2)])


def _parse_catalog(xml_text: str) -> list[_FileInfo]:
    root = ET.fromstring(xml_text)
    ns = {"t": "http://www.unidata.ucar.edu/namespaces/thredds/InvCatalog/v1.0"}
    files: list[_FileInfo] = []
    for d in root.findall(".//t:dataset", ns):
        name = d.get("name", "")
        if not name.endswith(".nc") or "lev2" not in name:
            continue
        parts = name.split(".")
        if len(parts) < 4:
            continue
        # Drop humidified measurements. A humidified nephelometer measures
        # scattering at elevated relative humidity and reads systematically higher
        # than a dry one, so averaging it together with dry files mixes two
        # different quantities. Excluding it was confirmed with Antti Hyvärinen
        # (FMI) in September 2026 — see docs/mcp-server-plan.md.
        #
        # Substring, not equality: the catalogue spells it three ways
        # (pm10_humidified, pm1_humidified, aerosol_humidified) and matching only
        # one of them would keep 19 of the 24 files this is meant to drop.
        if "humidified" in (parts[5] if len(parts) > 5 else ""):
            continue
        try:
            start = datetime.strptime(parts[1][:8], "%Y%m%d").date()
            revision = datetime.strptime(parts[2][:8], "%Y%m%d").date()

            # The extent comes from the duration field, not from parts[2]. That
            # field is when the file was revised, and it is typically years after
            # the data ends — 96% of the catalogue, median 7.9 years out. Treating
            # it as the end made every multi-year file claim years it does not
            # hold, and the slice for those years ran off the end of the array.
            duration = _parse_duration(parts[6]) if len(parts) > 6 else None
            if duration is None:
                # ~20 files in the catalogue. Fall back to the revision date and
                # let the time-coordinate check below reject what it must; the
                # alternative is dropping the file on a naming quirk.
                logger.debug("No duration field in %s; falling back to revision date", name)
                end = revision
            else:
                end = start + duration

            files.append(_FileInfo(
                station=parts[0],
                name=name,
                instrument=parts[3],
                start=start,
                end=end,
                revision=revision,
            ))
        except (ValueError, IndexError):
            continue
    return files


# ── Async OPeNDAP fetch helpers ───────────────────────────────────────────────

async def _fetch_opendap_ascii(client: httpx.AsyncClient, base_url: str, constraint: str) -> str:
    q = urllib.parse.quote(constraint, safe="")
    url = f"{base_url}.ascii?{q}"
    resp = await client.get(url, timeout=60.0)
    resp.raise_for_status()
    return resp.text


def _parse_first_section_floats(text: str) -> np.ndarray:
    """
    Extract floats from the FIRST data section of an OPeNDAP ASCII response.

    For Grid variables the response contains multiple sections separated by blank
    lines (array data, then each coordinate/map variable). We only want the first.
    """
    after_sep = text.split("-----\n", 1)[-1] if "-----" in text else text
    sections = re.split(r"\n\n+", after_sep.strip())
    if not sections:
        return np.array([])

    first = sections[0]
    lines = first.split("\n")

    vals: list[float] = []
    for line in lines[1:]:
        line = line.strip()
        if not line:
            continue
        line = re.sub(r"\[\d+\]", "", line)
        for tok in line.split(","):
            tok = tok.strip()
            if tok:
                try:
                    vals.append(float(tok))
                except ValueError:
                    pass

    return np.array(vals, dtype=float)


def _extract_coord_value(line: str, hemi_chars: str) -> tuple[float | None, str | None]:
    """
    Extract a coordinate value and optional hemisphere letter from one DAS line.

    Handles:
      - DMS:               62 13 12.0 S  /  62:13:12S  /  62°13'12"S
      - Decimal + suffix:  62.22S  /  62.22 S  /  "62.22S"
      - Signed float:      -62.22
    Returns (decimal_value, hemisphere_char_or_None).
    """
    # DMS: D[sep]M[sep]S [hemi]
    dms = re.search(
        r'(\d{1,3})[°\s:](\d{1,2})[\'°\s:]+(\d+\.?\d*)["\s]*([' + hemi_chars + r'])',
        line, re.IGNORECASE,
    )
    if dms:
        val = int(dms.group(1)) + int(dms.group(2)) / 60.0 + float(dms.group(3)) / 3600.0
        return val, dms.group(4).upper()

    # Decimal with optional direction suffix.
    # Lookbehind (?<![a-zA-Z\d]) prevents matching digits embedded in type names like "Float64".
    # Lookahead (?=\s*[;",]|\s*$) requires a clean terminator (semicolon, quote, end of line).
    dec = re.search(
        r'(?<![a-zA-Z\d])(-?\d+\.?\d*)\s*([' + hemi_chars + r'])?(?=\s*[;",]|\s*$)',
        line, re.IGNORECASE,
    )
    if dec:
        try:
            return float(dec.group(1)), (dec.group(2).upper() if dec.group(2) else None)
        except ValueError:
            pass
    return None, None


def _parse_das_coordinates(das_text: str) -> tuple[float | None, float | None]:
    """
    Parse lat/lon from a .das file, handling multiple coordinate styles:
      - Signed decimal:          Float64 geospatial_lat_min -62.22
      - Unsigned + hemi suffix:  String geospatial_lat_min "62.22S"
      - Separate hemi attribute: String station_lat_hemisphere "S"
      - DMS notation:            String station_latitude "62 13 12 S"
    Also recognises ebas_station_latitude/longitude (preferred — already signed)
    and station_latitude / station_longitude as attribute aliases.
    ebas_measurement_latitude is intentionally excluded; it can be unsigned/wrong
    (e.g. King Sejong: measurement_lat=62.22 but station_lat=-62.22).
    """
    lat = lon = lat_hemi = lon_hemi = None

    for line in das_text.split("\n"):
        low = line.lower()

        if lat is None and re.search(r'\b(ebas_station_latitude|geospatial_lat_min|station_latitude)\b', low):
            val, hemi = _extract_coord_value(line, "NS")
            if val is not None:
                lat, lat_hemi = val, hemi

        if lon is None and re.search(r'\b(ebas_station_longitude|geospatial_lon_min|station_longitude)\b', low):
            val, hemi = _extract_coord_value(line, "EW")
            if val is not None:
                lon, lon_hemi = val, hemi

        if lat_hemi is None and re.search(r'\b\w*lat\w*hemisphere\b', low):
            m = re.search(r'"([NS])"', line, re.IGNORECASE)
            if m:
                lat_hemi = m.group(1).upper()

        if lon_hemi is None and re.search(r'\b\w*lon\w*hemisphere\b', low):
            m = re.search(r'"([EW])"', line, re.IGNORECASE)
            if m:
                lon_hemi = m.group(1).upper()

    # Apply hemisphere signs to unsigned values
    if lat is not None and lat_hemi == "S" and lat > 0:
        lat = -lat
    if lon is not None and lon_hemi == "W" and lon > 0:
        lon = -lon

    return lat, lon


async def _fetch_station_meta_from_das(
    client: httpx.AsyncClient,
    fi: _FileInfo,
    actris_codes: set[str] | None = None,
) -> dict | None:
    try:
        url = f"{OPENDAP_BASE}/{fi.name}.das"
        resp = await client.get(url, timeout=30.0)
        text = resp.text

        lat, lon = _parse_das_coordinates(text)
        if lat is None or lon is None:
            return None

        networks = ""
        name = None
        ebas_station_name = None
        for line in text.split("\n"):
            if ebas_station_name is None:
                m = re.search(r'String ebas_station_name "(.*?)"', line, re.IGNORECASE)
                if m:
                    ebas_station_name = m.group(1).strip()
            if name is None and "title" in line.lower():
                title_m = re.search(r'String title "(.*?)"', line, re.IGNORECASE)
                if title_m:
                    title = title_m.group(1)
                    m = re.search(r"\bat (.+?) \(" + re.escape(fi.station) + r"\)", title, re.IGNORECASE)
                    if m:
                        name = m.group(1).strip()
                    else:
                        m = re.search(r"\bat (.+?)(?:\s+using\s|\s*$)", title, re.IGNORECASE)
                        if m:
                            name = m.group(1).strip()
            if not networks:
                m = re.search(r'String project "(.*?)"', line, re.IGNORECASE)
                if m:
                    found = list(dict.fromkeys(filter(None, (
                        _match_network(p) for p in m.group(1).split(',')
                    ))))
                    if found:
                        networks = ','.join(found)

        # Augment with ACTRIS DC lookup: if station is an ACTRIS National Facility,
        # ensure ACTRIS appears in networks even if the EBAS project field omits it.
        # Add the ACTRIS tag where the EBAS `project` field did not carry it.
        # Keyed by station code, so a renamed station keeps its tag.
        if actris_codes and fi.station in actris_codes and "ACTRIS" not in networks:
            networks = ("ACTRIS," + networks).rstrip(",") if networks else "ACTRIS"

        return {
            "name":     ebas_station_name or name or fi.station,
            "lat":      lat,
            "lon":      lon,
            "country":  fi.station[:2].upper(),
            "networks": networks,
        }
    except Exception:
        return None


@dataclass(frozen=True)
class _FileSample:
    """One file's contribution to a station-year.

    `valid_hours` is the hour-of-year indices holding a usable value, or None when
    the file's sampling could not be confirmed hourly — see `_compute_annual_mean`.
    None is not the same as an empty array: empty means "observed nothing", None
    means "we cannot say", and they must not be merged.
    """

    mean: float | None
    valid_hours: np.ndarray | None


def union_observed_hours(
    samples: list[tuple[str, _FileSample]], hours_in_year: int
) -> dict[str, float]:
    """Per station, the share of the year's hours holding at least one usable value.

    A union, not a sum. Most station-years have several files, they overlap in
    time, and they often carry different size cuts — adding their counts would put
    a station past 100% of a year it only partly observed.

    A station appears in the result only if at least one of its files had
    confirmable sampling. Absent means "cannot say"; 0.0 means "read, and held
    nothing". Callers must not collapse the two.
    """
    masks: dict[str, np.ndarray] = {}
    for station, sample in samples:
        if sample.valid_hours is None:
            continue
        mask = masks.get(station)
        if mask is None:
            mask = np.zeros(hours_in_year, dtype=bool)
            masks[station] = mask
        # Cast rather than trust the caller's dtype: an empty array built without
        # one is float64, and a float array cannot index a mask.
        valid_hours = np.asarray(sample.valid_hours, dtype=np.int64)
        mask[valid_hours[(valid_hours >= 0) & (valid_hours < hours_in_year)]] = True

    return {
        station: round(float(mask.sum()) / hours_in_year, 4)
        for station, mask in masks.items()
    }


#: How many points to sample when mapping a file's time coordinate. Enough to
#: locate a year boundary to within a few hours on any file in the catalogue,
#: while staying a small fraction of the data slice it saves us mis-reading.
_TIME_COARSE_POINTS = 2000

_TIME_UNITS_RE = re.compile(r"units\s+\"?\s*(second|minute|hour|day)s?\s+since\s+(\d{4}-\d{2}-\d{2})")

_UNIT_DAYS = {"second": 1 / 86400, "minute": 1 / 1440, "hour": 1 / 24, "day": 1.0}


@dataclass(frozen=True)
class _TimeAxis:
    """A file's time coordinate, sampled coarsely and expressed in days.

    The filename cannot answer where a year sits inside a file. Its duration field
    is nominal — `7y` on a file holding 51,674 hourly samples, where seven years is
    61,368 — and an internal gap moves every sample after it. Both were true of the
    catalogue, and between them they lost years and mislabelled others.

    So the year's bounds come from here instead: `coarse` holds every `stride`-th
    time value, converted to days since `epoch`, which is enough to bracket a year
    before reading the exact values in that bracket.
    """

    n: int
    stride: int
    coarse: np.ndarray
    epoch: date
    #: Days per raw time unit, so a raw `time` slice can be converted the same way
    #: `coarse` already has been.
    unit_days: float

    def value_for(self, day: date) -> float:
        return float((day - self.epoch).days)

    def bracket(self, first: date, last: date) -> tuple[int, int] | None:
        """Index range certain to contain [first, last), widened by one stride."""
        lo = int(np.searchsorted(self.coarse, self.value_for(first), side="left"))
        hi = int(np.searchsorted(self.coarse, self.value_for(last), side="right"))
        if lo >= len(self.coarse) and hi >= len(self.coarse):
            return None
        i0 = max(0, (lo - 1) * self.stride)
        i1 = min(self.n - 1, (hi + 1) * self.stride)
        return (i0, i1) if i1 >= i0 else None


async def _fetch_time_axis(
    client: httpx.AsyncClient, base_url: str, name: str
) -> _TimeAxis | None:
    """Read a file's length, time units and a coarse sample of its time values.

    One per file, cached by the caller — a seven-year file serves seven years, so
    the cost amortises across them.
    """
    try:
        dds = await client.get(f"{base_url}.dds", timeout=60.0)
        dds.raise_for_status()
        m = re.search(r"time\s*\[\s*time\s*=\s*(\d+)\s*\]", dds.text)
        if not m:
            logger.info("No time dimension in %s; cannot place a year in it", name)
            return None
        n = int(m.group(1))
        if n < 1:
            return None

        das = await client.get(f"{base_url}.das", timeout=60.0)
        das.raise_for_status()
        um = _TIME_UNITS_RE.search(das.text)
        if not um:
            logger.info("Unreadable time units in %s; skipping the file", name)
            return None
        unit_days = _UNIT_DAYS[um.group(1)]
        epoch = datetime.strptime(um.group(2), "%Y-%m-%d").date()

        stride = max(1, n // _TIME_COARSE_POINTS)
        text = await _fetch_opendap_ascii(client, base_url, f"time[0:{stride}:{n - 1}]")
        coarse = _parse_first_section_floats(text) * unit_days
        if coarse.size == 0:
            return None
        return _TimeAxis(
            n=n, stride=stride, coarse=coarse, epoch=epoch, unit_days=unit_days
        )

    except Exception as exc:
        logger.info("Could not read the time axis of %s: %s", name, exc)
        return None


async def _fetch_file_mean(
    client: httpx.AsyncClient,
    fi: _FileInfo,
    nc_var: str,
    year: int,
    target_wl: float,
    sem: asyncio.Semaphore,
    axis: _TimeAxis,
) -> _FileSample:
    """This file's contribution to one station-year, windowed by its own clock."""
    async with sem:
        base_url = f"{OPENDAP_BASE}/{fi.name}"
        jan1, next_jan1 = date(year, 1, 1), date(year + 1, 1, 1)

        bracket = axis.bracket(jan1, next_jan1)
        if bracket is None:
            return _FileSample(None, None)
        i0, i1 = bracket

        try:
            wl_idx: int | None = None
            if target_wl > 0:
                try:
                    wl_text = await _fetch_opendap_ascii(client, base_url, f"{nc_var}.Wavelength")
                    wl_vals = _parse_first_section_floats(wl_text)
                    if wl_vals.size > 0:
                        wl_idx = int(np.argmin(np.abs(wl_vals - target_wl)))
                except Exception as exc:
                    logger.debug("No wavelength axis in %s: %s", fi.name, exc)

            constraint = (
                f"{nc_var}[{wl_idx}][{i0}:{i1}]" if wl_idx is not None
                else f"{nc_var}[{i0}:{i1}]"
            )
            data_text = await _fetch_opendap_ascii(client, base_url, constraint)
            data = _parse_first_section_floats(data_text)

            time_text = await _fetch_opendap_ascii(client, base_url, f"time[{i0}:{i1}]")
            times = _parse_first_section_floats(time_text)

        except Exception as exc:
            # Previously `except Exception: return None`, which is how a defect
            # affecting most multi-year files stayed invisible for months. Whatever
            # goes wrong here, say so.
            logger.warning(
                "Fetch failed for %s [%d:%d] year %d: %s", fi.name, i0, i1, year, exc
            )
            return _FileSample(None, None)

        if data.size == 0 or times.size != data.size:
            logger.info(
                "%s year %d: %d values against %d timestamps; skipped",
                fi.name, year, data.size, times.size,
            )
            return _FileSample(None, None)

        # Trim the widened bracket to the year, using the file's own timestamps.
        # This is the whole point: nothing here infers a date from an index.
        days = times * axis.unit_days
        inside = (days >= axis.value_for(jan1)) & (days < axis.value_for(next_jan1))
        if not inside.any():
            return _FileSample(None, None)

        data, days = data[inside], days[inside]

        valid = (data > 0) & np.isfinite(data)
        mean = float(np.mean(data[valid])) if valid.any() else None

        # Hour of the year for each usable sample, from its timestamp rather than
        # its position. A gap in the file now costs coverage, as it should, instead
        # of shifting every sample after it.
        hours = np.floor((days[valid] - axis.value_for(jan1)) * 24).astype(np.int64)
        return _FileSample(mean, hours)
