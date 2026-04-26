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

TARGET_WAVELENGTH: dict[str, float] = {
    "N":          0.0,
    "scattering": 525.0,
    "absorption": 520.0,
}

_TTL = timedelta(hours=24)
_MAX_CONCURRENT = 20
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
        self._station_meta: dict[str, dict] = {}
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

        all_instrument = [f for f in catalog if f.instrument in instruments]

        rep_files: dict[str, _FileInfo] = {}
        for fi in all_instrument:
            if fi.station not in rep_files:
                rep_files[fi.station] = fi
        for fi in relevant:
            rep_files[fi.station] = fi

        sem = asyncio.Semaphore(_MAX_CONCURRENT)
        assert self._http

        means, metas = await asyncio.gather(
            asyncio.gather(*[_fetch_file_mean(self._http, f, nc_var, year, target_wl, sem) for f in relevant]),
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
                "data_coverage": 1.0 if values else 0.0,
                "networks":      meta.get("networks", ""),
            })

        self._set_cached(key, records)
        return records

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

    async def _get_station_meta(self, fi: _FileInfo, sem: asyncio.Semaphore) -> dict | None:
        if fi.station in self._station_meta:
            return self._station_meta[fi.station]
        async with sem:
            assert self._http
            return await _fetch_station_meta_from_das(self._http, fi)

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


async def _fetch_station_meta_from_das(client: httpx.AsyncClient, fi: _FileInfo) -> dict | None:
    try:
        url = f"{OPENDAP_BASE}/{fi.name}.das"
        resp = await client.get(url, timeout=30.0)
        text = resp.text

        KNOWN_NETWORKS = {"ACTRIS", "EMEP", "GAW-WDCA"}
        networks = ""

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
                    found = [p.strip() for p in m.group(1).split(',') if p.strip() in KNOWN_NETWORKS]
                    if found:
                        networks = ','.join(found)

        if lat is None or lon is None:
            return None

        return {
            "name":     name or fi.station,
            "lat":      lat,
            "lon":      lon,
            "country":  fi.station[:2].upper(),
            "networks": networks,
        }
    except Exception:
        return None


async def _fetch_file_mean(
    client: httpx.AsyncClient,
    fi: _FileInfo,
    nc_var: str,
    year: int,
    target_wl: float,
    sem: asyncio.Semaphore,
) -> float | None:
    async with sem:
        url = f"{OPENDAP_BASE}/{fi.name}"
        idx0, idx1 = _estimate_year_indices(fi, year)
        return await _compute_annual_mean(client, url, nc_var, idx0, idx1, target_wl)


def _estimate_year_indices(fi: _FileInfo, year: int) -> tuple[int, int]:
    effective_start = max(fi.start, date(year, 1, 1))
    effective_end   = min(fi.end,   date(year + 1, 1, 1))
    idx0 = (effective_start - fi.start).days * 24
    idx1 = (effective_end   - fi.start).days * 24 - 1
    return max(0, idx0), max(0, idx1)


async def _compute_annual_mean(
    client: httpx.AsyncClient,
    base_url: str,
    nc_var: str,
    idx0: int,
    idx1: int,
    target_wl: float = 0.0,
) -> float | None:
    if idx1 < idx0:
        return None

    try:
        wl_idx: int | None = None
        if target_wl > 0:
            try:
                wl_text = await _fetch_opendap_ascii(client, base_url, f"{nc_var}.Wavelength")
                wl_vals = _parse_first_section_floats(wl_text)
                if wl_vals.size > 0:
                    wl_idx = int(np.argmin(np.abs(wl_vals - target_wl)))
            except Exception:
                pass

        constraint = (
            f"{nc_var}[{wl_idx}][{idx0}:{idx1}]" if wl_idx is not None
            else f"{nc_var}[{idx0}:{idx1}]"
        )

        data_text = await _fetch_opendap_ascii(client, base_url, constraint)
        data = _parse_first_section_floats(data_text)

        if data.size == 0:
            return None

        valid = data[(data > 0) & np.isfinite(data)]
        return float(np.mean(valid)) if valid.size > 0 else None

    except Exception:
        return None
