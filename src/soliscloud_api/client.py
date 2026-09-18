import asyncio
import json
import logging
import random
import time
from collections import deque
from typing import Any

import httpx
from pydantic import ValidationError

from .auth import build_auth_headers
from .errors import (
    SolisAPIError,
    SolisAuthError,
    SolisClockSkewError,
    SolisError,
    SolisRateLimitError,
    SolisTransportError,
)
from .models import InverterDetail, InverterListResponse, SolisResponse
from .settings import Settings, get_settings

_LOGGER = logging.getLogger(__name__)

# SolisCloud documents "three times every five seconds for the same IP".
RATE_LIMIT_CALLS = 3
RATE_LIMIT_PERIOD = 5.0

DEFAULT_MAX_ATTEMPTS = 3


def _parse_retry_after(value: str | None) -> float | None:
    """Seconds from a Retry-After header, or None. HTTP-date form is not supported."""
    if not value:
        return None
    try:
        return max(0.0, float(value.strip()))
    except ValueError:
        return None


class _RateLimiter:
    """Sliding window limiter, shared by every call on one client instance."""

    def __init__(self, max_calls: int = RATE_LIMIT_CALLS, period: float = RATE_LIMIT_PERIOD):
        self._max_calls = max_calls
        self._period = period
        self._starts: deque[float] = deque()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        async with self._lock:
            while True:
                now = time.monotonic()
                while self._starts and now - self._starts[0] >= self._period:
                    self._starts.popleft()
                if len(self._starts) < self._max_calls:
                    self._starts.append(now)
                    return
                await asyncio.sleep(self._period - (now - self._starts[0]))


class SolisCloudClient:
    """Async SolisCloud API client.

    Pass an httpx.AsyncClient to reuse an existing connection pool (Home Assistant
    supplies its own); otherwise one is created and closed with this client.
    """

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        client: httpx.AsyncClient | None = None,
        max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    ):
        s = settings or get_settings()
        self._api_id = s.solis_id.get_secret_value()
        self._api_secret = s.solis_secret.get_secret_value()
        self._max_attempts = max_attempts
        self._limiter = _RateLimiter()
        self._base_url = str(s.solis_url).rstrip("/")
        # Applied per request, not on the client. A caller-supplied client carries its
        # own timeout -- Home Assistant's shared client uses httpx's 5s default, which
        # is far below this API's ~16s median and would time out on every call.
        self._timeout = s.solis_timeout
        self._owns_client = client is None
        # No base_url either: endpoints are joined explicitly below, so a client with
        # no base_url works unchanged.
        self._client = client or httpx.AsyncClient(timeout=s.solis_timeout)
        # Populated on every request so `probe` can show exactly what was signed.
        self.last_request_debug: dict[str, str] = {}

    async def __aenter__(self) -> SolisCloudClient:
        return self

    async def __aexit__(self, *args: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    # --- transport ---------------------------------------------------------

    async def _send_once(self, endpoint: str, body_str: str) -> Any:
        await self._limiter.acquire()
        headers, sign_string = build_auth_headers(self._api_id, self._api_secret, body_str, endpoint)
        self.last_request_debug = {
            "endpoint": endpoint,
            "body": body_str,
            "date": headers["Date"],
            "content_md5": headers["Content-MD5"],
            "sign_string": sign_string,
        }

        try:
            response = await self._client.post(
                f"{self._base_url}{endpoint}",
                content=body_str,
                headers=headers,
                timeout=self._timeout,
            )
        except httpx.TimeoutException as err:
            raise SolisTransportError(f"timed out: {err}", endpoint) from err
        except httpx.HTTPError as err:
            raise SolisTransportError(str(err), endpoint) from err

        self.last_request_debug["server_date"] = response.headers.get("Date", "")
        self.last_request_debug["status"] = str(response.status_code)

        self._raise_for_status(response, endpoint, body_str, headers["Date"])

        try:
            payload = response.json()
        except ValueError as err:
            raise SolisTransportError(f"response was not JSON: {response.text[:200]!r}", endpoint) from err

        try:
            resp = SolisResponse.model_validate(payload)
        except ValidationError as err:
            raise SolisTransportError(f"unexpected response shape: {err}", endpoint) from err
        if not resp.success or resp.code != "0":
            raise self._api_error(resp, endpoint, body_str)
        return resp.data

    @staticmethod
    def _raise_for_status(response: httpx.Response, endpoint: str, body_str: str, local_date: str) -> None:
        status = response.status_code
        if status in (401, 403):
            raise SolisAuthError(str(status), response.text[:200], endpoint)
        if status == 408:
            raise SolisClockSkewError(local_date, response.headers.get("Date"))
        if status == 429:
            raise SolisRateLimitError(
                response.text[:200] or "too many requests",
                _parse_retry_after(response.headers.get("Retry-After")),
            )
        if status >= 500:
            raise SolisTransportError(f"server returned {status}", endpoint)
        if status != 200:
            raise SolisAPIError(str(status), response.text[:200], endpoint, body_str)

    @staticmethod
    def _api_error(resp: SolisResponse, endpoint: str, body_str: str) -> SolisError:
        """Map a non-zero API code onto the most specific error we can justify.

        Only the rate-limit case is inferred from the message; SolisCloud's numeric
        code table is not published, so everything else stays a plain SolisAPIError
        rather than being guessed at. `probe` surfaces real codes so this can be
        tightened later with evidence.
        """
        lowered = (resp.msg or "").lower()
        if "frequent" in lowered or "too many" in lowered:
            return SolisRateLimitError(resp.msg)
        return SolisAPIError(resp.code, resp.msg, endpoint, body_str)

    async def _request(self, endpoint: str, body: dict | None = None) -> Any:
        body_str = json.dumps(body or {})
        delay = 1.0
        for attempt in range(1, self._max_attempts + 1):
            try:
                return await self._send_once(endpoint, body_str)
            except (SolisRateLimitError, SolisClockSkewError, SolisTransportError) as err:
                if attempt == self._max_attempts:
                    _LOGGER.error("%s failed after %d attempts: %s", endpoint, attempt, err)
                    raise
                retry_after = getattr(err, "retry_after", None)
                if retry_after is not None:
                    wait = retry_after  # honour the server, including 0
                elif isinstance(err, SolisRateLimitError):
                    # Backing off less than the limiter's own window guarantees the
                    # retry lands inside the window that rejected us.
                    wait = max(delay, RATE_LIMIT_PERIOD)
                else:
                    wait = delay
                wait += random.uniform(0, wait * 0.3)
                _LOGGER.warning("%s failed (%s); retrying in %.1fs", endpoint, err, wait)
                await asyncio.sleep(wait)
                delay *= 2
        raise AssertionError("unreachable")

    @staticmethod
    def _validate[T](model: type[T], data: Any, endpoint: str) -> T:
        """Model validation failures are reported as SolisError, not raw pydantic."""
        try:
            return model.model_validate(data)
        except ValidationError as err:
            raise SolisTransportError(f"unexpected payload shape: {err}", endpoint) from err

    # --- inverter endpoints ------------------------------------------------

    async def inverter_list(self, page_no: int = 1, page_size: int = 100) -> InverterListResponse:
        data = await self._request("/v1/api/inverterList", {"pageNo": page_no, "pageSize": page_size})
        return self._validate(InverterListResponse, data, "/v1/api/inverterList")

    async def inverter_detail(
        self, *, inverter_id: str | None = None, inverter_sn: str | None = None
    ) -> InverterDetail:
        body: dict = {}
        if inverter_id:
            body["id"] = inverter_id
        if inverter_sn:
            body["sn"] = inverter_sn
        data = await self._request("/v1/api/inverterDetail", body)
        return self._validate(InverterDetail, data, "/v1/api/inverterDetail")

    async def inverter_day(self, inverter_id: str, date: str, timezone: int = 8) -> dict:
        return await self._request(
            "/v1/api/inverterDay",
            {"id": inverter_id, "money": "USD", "time": date, "timeZone": timezone},
        )

    async def inverter_month(self, inverter_id: str, month: str) -> dict:
        return await self._request("/v1/api/inverterMonth", {"id": inverter_id, "money": "USD", "month": month})

    async def inverter_year(self, inverter_id: str, year: str) -> dict:
        return await self._request("/v1/api/inverterYear", {"id": inverter_id, "money": "USD", "year": year})

    # --- station endpoints -------------------------------------------------

    async def station_list(self, page_no: int = 1, page_size: int = 100) -> dict:
        return await self._request("/v1/api/userStationList", {"pageNo": page_no, "pageSize": page_size})

    async def station_detail(self, station_id: str) -> dict:
        return await self._request("/v1/api/stationDetail", {"id": station_id})

    async def station_day(self, station_id: str, date: str, timezone: int = 8) -> dict:
        return await self._request(
            "/v1/api/stationDay",
            {"id": station_id, "money": "USD", "time": date, "timeZone": timezone},
        )

    async def station_month(self, station_id: str, month: str) -> dict:
        return await self._request("/v1/api/stationMonth", {"id": station_id, "money": "USD", "month": month})

    async def station_year(self, station_id: str, year: str) -> dict:
        return await self._request("/v1/api/stationYear", {"id": station_id, "money": "USD", "year": year})

    async def station_all(self, station_id: str) -> dict:
        return await self._request("/v1/api/stationAll", {"id": station_id})

    # --- collector endpoints -----------------------------------------------

    async def collector_list(self, page_no: int = 1, page_size: int = 100) -> dict:
        return await self._request("/v1/api/collectorList", {"pageNo": page_no, "pageSize": page_size})

    async def collector_detail(self, *, collector_id: str | None = None, collector_sn: str | None = None) -> dict:
        body: dict = {}
        if collector_id:
            body["id"] = collector_id
        if collector_sn:
            body["sn"] = collector_sn
        return await self._request("/v1/api/collectorDetail", body)

    # --- alarm endpoint ----------------------------------------------------

    async def alarm_list(self, station_id: str, page_no: int = 1, page_size: int = 100) -> dict:
        return await self._request(
            "/v1/api/alarmList",
            {"stationId": station_id, "pageNo": page_no, "pageSize": page_size},
        )
