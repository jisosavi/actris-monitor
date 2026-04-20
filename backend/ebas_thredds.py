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
import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

import httpx
import numpy as np

CATALOG_URL = "https://thredds.nilu.no/thredds/catalog/ebas/catalog.xml"
OPENDAP_BASE = "https://thredds.nilu.no/thredds/dodsC/ebas"

INSTRUMENT_MAP: dict[str, list[str]] = {
    "N":          ["cpc"],
    "scattering": ["nephelometer"],
    "absorption": ["filter_absorption_photometer"],
}

NC_VAR: dict[str, str] = {
    "N":          "particle_number_concentration_amean",
    "scattering": "aerosol_light_scattering_coefficient_amean",
    "absorption": "aerosol_absorption_coefficient_amean",
}

# Per-variable target wavelength (nm) as specified in the product definition.
# The file's actual wavelengths may differ; we pick the nearest available.
TARGET_WAVELENGTH: dict[str, float] = {
    "N":          0.0,      # no wavelength dimension
    "scattering": 525.0,    # nephelometers typically have 450/525/635 nm
    "absorption": 520.0,    # filter photometers typically have 520/530 nm
}

_TTL = timedelta(hours=24)
_MAX_CONCURRENT = 15
_EPOCH = date(1900, 1, 1)


@dataclass
class _FileInfo:
    station: str
    name: str
    instrument: str
    start: date
    end: date


class EbasThreddsClient:
    def __init__(self) -> None:
        self._http: httpx.AsyncClient | None = None
        self._catalog: tuple[list[_FileInfo], datetime] | None = None
        self._station_meta: dict[str, dict] = {}   # GAW code -> {name, lat, lon, country}
        self._data_cache: dict[str, tuple[Any, datetime]] = {}

    async def start(self) -> None:
        self._http = httpx.AsyncClient(timeout=60.0)

    async def close(self) -> None:
        if self._http:
            await self._http.aclose()

    async def fetch_measurements(self, year: int, variable: str) -> list[dict]:
        """
        Return enriched station records for compute_annual_stats:
          [{id, name, lat, lon, country, mean, data_coverage}, ...]
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

        # One representative file per station for metadata lookup
        rep_files: dict[str, _FileInfo] = {}
        for fi in relevant:
            if fi.station not in rep_files:
                rep_files[fi.station] = fi

        sem = asyncio.Semaphore(_MAX_CONCURRENT)

        # Fetch means and station metadata concurrently
        means, metas = await asyncio.gather(
            asyncio.gather(*[_fetch_file_mean(f, nc_var, year, target_wl, sem) for f in relevant]),
            asyncio.gather(*[self._get_station_meta(fi, sem) for fi in rep_files.values()]),
        )

        for fi, meta in zip(rep_files.values(), metas):
            if meta and fi.station not in self._station_meta:
                self._station_meta[fi.station] = meta

        by_station: dict[str, list[float]] = {}
        for fi, mean in zip(relevant, means):
            if mean is not None:
                by_station.setdefault(fi.station, []).append(mean)

        records = []
        for station_code, values in by_station.items():
            meta = self._station_meta.get(station_code)
            if meta is None:
                continue
            records.append({
                "id":            station_code,
                "name":          meta["name"],
                "lat":           meta["lat"],
                "lon":           meta["lon"],
                "country":       meta["country"],
                "mean":          float(np.mean(values)),
                "data_coverage": 1.0,
            })

        self._set_cached(key, records)
        return records

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

    async def _get_station_meta(self, fi: _FileInfo, sem: asyncio.Semaphore) -> dict | None:
        if fi.station in self._station_meta:
            return self._station_meta[fi.station]
        async with sem:
            return await asyncio.to_thread(_fetch_station_meta_from_das, fi)

    def _get_cached(self, key: str) -> Any | None:
        if key in self._data_cache:
            data, ts = self._data_cache[key]
            if datetime.now() - ts < _TTL:
                return data
        return None

    def _set_cached(self, key: str, data: Any) -> None:
        self._data_cache[key] = (data, datetime.now())


# ── Catalog parsing ───────────────────────────────────────────────────────────

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
        try:
            start = datetime.strptime(parts[1][:8], "%Y%m%d").date()
            end   = datetime.strptime(parts[2][:8], "%Y%m%d").date()
            files.append(_FileInfo(
                station=parts[0],
                name=name,
                instrument=parts[3],
                start=start,
                end=end,
            ))
        except (ValueError, IndexError):
            continue
    return files


# ── OPeNDAP fetch helpers ─────────────────────────────────────────────────────

def _fetch_station_meta_from_das(fi: _FileInfo) -> dict | None:
    """
    Fetch station name, lat, lon from the OPeNDAP .das attribute file.
    Coordinates live in geospatial_lat_min / geospatial_lon_min global attrs.
    Station name is parsed from the 'title' global attribute.
    """
    try:
        url = f"{OPENDAP_BASE}/{fi.name}.das"
        with urllib.request.urlopen(url, timeout=30) as r:
            text = r.read().decode("utf-8", errors="replace")

        lat = lon = name = None
        for line in text.split("\n"):
            if lat is None:
                m = re.search(r"geospatial_lat_min\s+([-\d.]+)", line)
                if m:
                    lat = float(m.group(1))
            if lon is None:
                m = re.search(r"geospatial_lon_min\s+([-\d.]+)", line)
                if m:
                    lon = float(m.group(1))
            if name is None:
                # title: "...at StationName (AT0034G) using ..."
                m = re.search(r"\bat (.+?) \(" + re.escape(fi.station) + r"\)", line, re.IGNORECASE)
                if m:
                    name = m.group(1).strip()

        if lat is None or lon is None:
            return None

        return {
            "name":    name or fi.station,
            "lat":     lat,
            "lon":     lon,
            "country": fi.station[:2].upper(),
        }
    except Exception:
        return None


async def _fetch_file_mean(
    fi: _FileInfo, nc_var: str, year: int, target_wl: float, sem: asyncio.Semaphore
) -> float | None:
    async with sem:
        url = f"{OPENDAP_BASE}/{fi.name}"
        idx0, idx1 = _estimate_year_indices(fi, year)
        return await asyncio.to_thread(_compute_annual_mean, url, nc_var, idx0, idx1, target_wl)


def _estimate_year_indices(fi: _FileInfo, year: int) -> tuple[int, int]:
    """
    Estimate hourly index range for a calendar year within an EBAS file.
    Each EBAS hourly file has exactly one record per hour; index 0 = first hour.
    """
    effective_start = max(fi.start, date(year, 1, 1))
    effective_end   = min(fi.end,   date(year + 1, 1, 1))
    idx0 = (effective_start - fi.start).days * 24
    idx1 = (effective_end   - fi.start).days * 24 - 1
    return max(0, idx0), max(0, idx1)


def _fetch_opendap_ascii(base_url: str, constraint: str) -> str:
    q = urllib.parse.quote(constraint, safe="")
    url = f"{base_url}.ascii?{q}"
    with urllib.request.urlopen(url, timeout=60) as r:
        return r.read().decode("utf-8", errors="replace")


def _parse_first_section_floats(text: str) -> np.ndarray:
    """
    Extract floats from the FIRST data section of an OPeNDAP ASCII response.

    For Grid variables the response contains multiple sections separated by blank
    lines (array data, then each coordinate/map variable). We only want the first.

    Section format:
      variable_path[dim1][dim2]
      [row_idx], val1, val2, ...   ← row-index prefix for 2-D slices
    """
    after_sep = text.split("-----\n", 1)[-1] if "-----" in text else text
    sections = re.split(r"\n\n+", after_sep.strip())
    if not sections:
        return np.array([])

    first = sections[0]
    lines = first.split("\n")

    vals: list[float] = []
    for line in lines[1:]:          # skip header line (variable_path[dims])
        line = line.strip()
        if not line:
            continue
        line = re.sub(r"\[\d+\]", "", line)     # strip row-index markers like [0]
        for tok in line.split(","):
            tok = tok.strip()
            if tok:
                try:
                    vals.append(float(tok))
                except ValueError:
                    pass

    return np.array(vals, dtype=float)


def _compute_annual_mean(
    base_url: str, nc_var: str, idx0: int, idx1: int, target_wl: float = 0.0
) -> float | None:
    """
    Synchronous: fetch a year-slice via OPeNDAP ASCII and return the annual mean.
    Runs in a thread pool via asyncio.to_thread().
    """
    if idx1 < idx0:
        return None

    try:
        # Check for Wavelength dimension; select closest to TARGET_WAVELENGTH_NM
        wl_idx: int | None = None
        if target_wl > 0:
            try:
                wl_text = _fetch_opendap_ascii(base_url, f"{nc_var}.Wavelength")
                wl_vals = _parse_first_section_floats(wl_text)
                if wl_vals.size > 0:
                    wl_idx = int(np.argmin(np.abs(wl_vals - target_wl)))
            except Exception:
                pass

        if wl_idx is not None:
            constraint = f"{nc_var}[{wl_idx}][{idx0}:{idx1}]"
        else:
            constraint = f"{nc_var}[{idx0}:{idx1}]"

        data_text = _fetch_opendap_ascii(base_url, constraint)
        data = _parse_first_section_floats(data_text)

        if data.size == 0:
            return None

        valid = data[(data > 0) & np.isfinite(data)]
        return float(np.mean(valid)) if valid.size > 0 else None

    except Exception:
        return None
