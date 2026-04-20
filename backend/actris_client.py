"""
ACTRIS API client with 24-hour in-memory TTL cache.

Base URL: https://prod-actris-md2.nilu.no
Swagger:  https://prod-actris-md2.nilu.no/index.html

TODO: Verify exact endpoint paths and query parameters against the swagger.
The endpoints used here follow the documented patterns but field names in
responses may differ — update the column mapping in aggregation.py accordingly.
"""

import httpx
from datetime import datetime, timedelta
from typing import Any

ACTRIS_BASE = "https://prod-actris-md2.nilu.no"
_TTL = timedelta(hours=24)


class ActrisClient:
    def __init__(self) -> None:
        self._client: httpx.AsyncClient | None = None
        self._cache: dict[str, tuple[Any, datetime]] = {}

    async def start(self) -> None:
        self._client = httpx.AsyncClient(
            base_url=ACTRIS_BASE,
            timeout=30.0,
            headers={"Accept": "application/json"},
        )

    async def close(self) -> None:
        if self._client:
            await self._client.aclose()

    def _cached(self, key: str) -> Any | None:
        if key in self._cache:
            data, ts = self._cache[key]
            if datetime.now() - ts < _TTL:
                return data
        return None

    def _store(self, key: str, data: Any) -> None:
        self._cache[key] = (data, datetime.now())

    async def fetch_facilities(self) -> list[dict]:
        """
        Fetch all ACTRIS measurement facilities (stations) with coordinates.

        TODO: Confirm endpoint — likely GET /Facilities
        Expected response fields:
          identifier, name, latitude, longitude, country, instrumentTypes
        """
        cached = self._cached("facilities")
        if cached is not None:
            return cached

        assert self._client
        resp = await self._client.get("/Facilities")
        resp.raise_for_status()
        data: list[dict] = resp.json()
        self._store("facilities", data)
        return data

    async def fetch_measurements(self, year: int, parameter: str) -> list[dict]:
        """
        Fetch annual mean observations for a parameter across all ACTRIS stations.

        TODO: Confirm endpoint and params against swagger. Candidate endpoints:
          GET /Observations  — with startDate/endDate + parameter filter
          GET /DataProducts  — if data is pre-aggregated by year

        Expected response per record:
          facility_id, facility_name, latitude, longitude, country_code,
          mean_value, data_coverage (0-1 fraction of the year with data)
        """
        key = f"{year}:{parameter}"
        cached = self._cached(key)
        if cached is not None:
            return cached

        assert self._client
        resp = await self._client.get(
            "/Observations",
            params={
                "parameter": parameter,
                "startDate": f"{year}-01-01",
                "endDate": f"{year}-12-31",
                "statistics": "annual_mean",
            },
        )
        resp.raise_for_status()
        data: list[dict] = resp.json()
        self._store(key, data)
        return data
