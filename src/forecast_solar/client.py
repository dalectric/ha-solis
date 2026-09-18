import json
import time
from pathlib import Path

import httpx

from .models import ForecastResult, PVArray, PVSite

DEFAULT_CACHE_DIR = Path.home() / ".cache" / "forecast_solar"
DEFAULT_CACHE_TTL = 1200  # 20 min — forecast.solar updates every 15 min, free plan allows 12 calls/hour


class ForecastSolarClient:
    BASE_URL = "https://api.forecast.solar"

    def __init__(
        self,
        site: PVSite,
        *,
        cache_dir: Path = DEFAULT_CACHE_DIR,
        cache_ttl: int = DEFAULT_CACHE_TTL,
    ):
        self._site = site
        self._cache_dir = cache_dir
        self._cache_ttl = cache_ttl
        self._client = httpx.Client(timeout=30.0)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self._client.close()

    def close(self):
        self._client.close()

    def _estimate_url(self, array: PVArray) -> str:
        return (
            f"{self.BASE_URL}/estimate"
            f"/{self._site.latitude}/{self._site.longitude}"
            f"/{array.decline}/{array.azimuth}/{array.nominal_capacity}"
        )

    def _check_url(self) -> str:
        return f"{self.BASE_URL}/check/{self._site.latitude}/{self._site.longitude}"

    def _cache_path(self, array: PVArray) -> Path | None:
        if self._cache_dir is None:
            return None
        return self._cache_dir / f"forecast_solar_{array.name}.json"

    def _load_cache(self, array: PVArray, *, ignore_ttl: bool = False) -> dict | None:
        path = self._cache_path(array)
        if not path or not path.exists():
            return None

        if not ignore_ttl:
            age = time.time() - path.stat().st_mtime
            if age > self._cache_ttl:
                return None

        return json.loads(path.read_text())

    def _save_cache(self, array: PVArray, data: dict) -> None:
        path = self._cache_path(array)
        if path:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(data, indent=2))

    def check(self) -> dict:
        response = self._client.get(self._check_url())
        response.raise_for_status()
        return response.json()

    def estimate(self, array: PVArray) -> ForecastResult:
        cached = self._load_cache(array)
        if cached:
            return ForecastResult(array_name=array.name, **cached["result"])

        response = self._client.get(self._estimate_url(array))

        if response.status_code == 429:
            # Rate limited — fall back to stale cache if available
            stale = self._load_cache(array, ignore_ttl=True)
            if stale:
                return ForecastResult(array_name=array.name, **stale["result"])
            response.raise_for_status()

        response.raise_for_status()
        data = response.json()

        self._save_cache(array, data)

        return ForecastResult(array_name=array.name, **data["result"])

    def estimate_all(self) -> list[ForecastResult]:
        return [self.estimate(array) for array in self._site.arrays]

    def estimate_aggregated(self) -> ForecastResult:
        results = self.estimate_all()

        def _sum_dicts(*dicts: dict[str, float]) -> dict[str, float]:
            all_keys = dict.fromkeys(k for d in dicts for k in d)
            return {k: sum(d.get(k, 0) for d in dicts) for k in all_keys}

        return ForecastResult(
            array_name="Total",
            watts=_sum_dicts(*(r.watts for r in results)),
            watt_hours_period=_sum_dicts(*(r.watt_hours_period for r in results)),
            watt_hours=_sum_dicts(*(r.watt_hours for r in results)),
            watt_hours_day=_sum_dicts(*(r.watt_hours_day for r in results)),
        )
