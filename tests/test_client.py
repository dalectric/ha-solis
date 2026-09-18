import asyncio
import time

import httpx
import pytest
import respx

from soliscloud_api.client import RATE_LIMIT_CALLS, RATE_LIMIT_PERIOD, SolisCloudClient, _RateLimiter
from soliscloud_api.errors import (
    SolisAPIError,
    SolisAuthError,
    SolisClockSkewError,
    SolisRateLimitError,
    SolisTransportError,
)
from soliscloud_api.settings import Settings

BASE = "https://api.test.com"
LIST_URL = f"{BASE}/v1/api/inverterList"
DETAIL_URL = f"{BASE}/v1/api/inverterDetail"


def _make_settings() -> Settings:
    return Settings(solis_id="test-id", solis_secret="test-secret", solis_url=BASE)


def _client(**kwargs) -> SolisCloudClient:
    kwargs.setdefault("max_attempts", 1)
    return SolisCloudClient(settings=_make_settings(), **kwargs)


INVERTER_LIST_RESPONSE = {
    "success": True,
    "code": "0",
    "msg": "success",
    "data": {
        "inverterStatusVo": {"all": 1, "normal": 1, "fault": 0, "offline": 0},
        "page": {
            "current": 1,
            "pages": 1,
            "total": 1,
            "size": 100,
            "records": [
                {
                    "id": "inv-001",
                    "sn": "SN123",
                    "stationId": "st-001",
                    "state": 1,
                    "pac": 2500.0,
                    "etoday": 12.5,
                    "etotal": 10.0,
                }
            ],
        },
    },
}

EMPTY_LIST_RESPONSE = {
    "success": True,
    "code": "0",
    "msg": "success",
    "data": {
        "inverterStatusVo": {"all": 0, "normal": 0, "fault": 0, "offline": 0},
        "page": {"current": 1, "pages": 0, "total": 0, "size": 100, "records": []},
    },
}

INVERTER_DETAIL_RESPONSE = {
    "success": True,
    "code": "0",
    "msg": "success",
    "data": {
        "id": "inv-001",
        "sn": "SN123",
        "stationId": "st-001",
        "state": 1,
        "pac": 2500.0,
        "batteryCapacitySoc": 75.0,
        "batteryPower": -200.0,
        "familyLoadPower": 1800.0,
        "psum": -500.0,
        "uAc1": "230.5",
        "iAc1": "10.8",
        "fac": 50.01,
    },
}


class TestHappyPath:
    @respx.mock
    async def test_inverter_list(self):
        respx.post(LIST_URL).mock(return_value=httpx.Response(200, json=INVERTER_LIST_RESPONSE))
        async with _client() as client:
            result = await client.inverter_list()
        assert result.inverter_status_vo.all == 1
        assert len(result.records) == 1
        assert result.records[0].sn == "SN123"
        assert result.records[0].pac == 2500.0

    @respx.mock
    async def test_inverter_detail(self):
        respx.post(DETAIL_URL).mock(return_value=httpx.Response(200, json=INVERTER_DETAIL_RESPONSE))
        async with _client() as client:
            detail = await client.inverter_detail(inverter_id="inv-001")
        assert detail.battery_capacity_soc == 75.0
        assert detail.battery_power == -200.0
        assert detail.u_ac1 == 230.5
        assert detail.fac == 50.01

    @respx.mock
    async def test_request_sends_auth_headers(self):
        respx.post(LIST_URL).mock(return_value=httpx.Response(200, json=INVERTER_LIST_RESPONSE))
        async with _client() as client:
            await client.inverter_list()
        request = respx.calls[0].request
        assert request.headers["Authorization"].startswith("API test-id:")
        assert request.headers["Content-Type"] == "application/json"
        assert "Content-MD5" in request.headers
        assert "Date" in request.headers

    @respx.mock
    async def test_signed_body_is_the_body_that_is_sent(self):
        """The MD5 must describe the exact bytes on the wire, not a re-serialisation."""
        respx.post(LIST_URL).mock(return_value=httpx.Response(200, json=INVERTER_LIST_RESPONSE))
        async with _client() as client:
            await client.inverter_list()
        request = respx.calls[0].request
        from soliscloud_api.auth import compute_content_md5

        assert request.headers["Content-MD5"] == compute_content_md5(request.content.decode())


class TestFailureCausesAreDistinct:
    """Each cause must raise its own type.

    The integration this replaces returned an empty dict for every one of these, so
    "No inverters found" was logged whether the key was wrong, the clock was skewed,
    the rate limit was hit, or the account genuinely had no inverters.
    """

    @respx.mock
    async def test_empty_list_is_not_an_error(self):
        respx.post(LIST_URL).mock(return_value=httpx.Response(200, json=EMPTY_LIST_RESPONSE))
        async with _client() as client:
            result = await client.inverter_list()
        assert result.records == []

    @pytest.mark.parametrize("status", [401, 403])
    async def test_auth_failure(self, status):
        with respx.mock:
            respx.post(LIST_URL).mock(return_value=httpx.Response(status, text="forbidden"))
            async with _client() as client:
                with pytest.raises(SolisAuthError):
                    await client.inverter_list()

    @respx.mock
    async def test_clock_skew(self):
        respx.post(LIST_URL).mock(
            return_value=httpx.Response(408, headers={"Date": "Wed, 17 Sep 2026 10:00:00 GMT"}, text="")
        )
        async with _client() as client:
            with pytest.raises(SolisClockSkewError) as exc:
                await client.inverter_list()
        assert exc.value.server_date == "Wed, 17 Sep 2026 10:00:00 GMT"

    @respx.mock
    async def test_rate_limited_by_status(self):
        respx.post(LIST_URL).mock(return_value=httpx.Response(429, text="too many requests"))
        async with _client() as client:
            with pytest.raises(SolisRateLimitError):
                await client.inverter_list()

    @respx.mock
    async def test_rate_limited_by_message(self):
        body = {"success": False, "code": "B0110", "msg": "Request too frequent", "data": None}
        respx.post(LIST_URL).mock(return_value=httpx.Response(200, json=body))
        async with _client() as client:
            with pytest.raises(SolisRateLimitError):
                await client.inverter_list()

    @respx.mock
    async def test_server_error_is_transport(self):
        respx.post(LIST_URL).mock(return_value=httpx.Response(500, text="Internal Server Error"))
        async with _client() as client:
            with pytest.raises(SolisTransportError):
                await client.inverter_list()

    @respx.mock
    async def test_timeout_is_transport(self):
        respx.post(LIST_URL).mock(side_effect=httpx.ConnectTimeout("timed out"))
        async with _client() as client:
            with pytest.raises(SolisTransportError):
                await client.inverter_list()

    @respx.mock
    async def test_non_json_is_transport(self):
        respx.post(LIST_URL).mock(return_value=httpx.Response(200, text="<html>gateway</html>"))
        async with _client() as client:
            with pytest.raises(SolisTransportError):
                await client.inverter_list()

    @respx.mock
    async def test_unexpected_shape_is_transport(self):
        respx.post(LIST_URL).mock(return_value=httpx.Response(200, json={"nothing": "useful"}))
        async with _client() as client:
            with pytest.raises(SolisTransportError):
                await client.inverter_list()

    @respx.mock
    async def test_api_error_code(self):
        body = {"success": False, "code": "1001", "msg": "invalid parameters", "data": None}
        respx.post(LIST_URL).mock(return_value=httpx.Response(200, json=body))
        async with _client() as client:
            with pytest.raises(SolisAPIError) as exc:
                await client.inverter_list()
        assert exc.value.code == "1001"
        assert "invalid parameters" in exc.value.msg
        assert exc.value.endpoint == "/v1/api/inverterList"


class TestRetry:
    @respx.mock
    async def test_transport_error_is_retried_then_succeeds(self):
        respx.post(LIST_URL).mock(
            side_effect=[
                httpx.Response(500, text="boom"),
                httpx.Response(200, json=INVERTER_LIST_RESPONSE),
            ]
        )
        async with _client(max_attempts=3) as client:
            result = await client.inverter_list()
        assert len(result.records) == 1
        assert len(respx.calls) == 2

    @respx.mock
    async def test_auth_error_is_never_retried(self):
        respx.post(LIST_URL).mock(return_value=httpx.Response(401, text="nope"))
        async with _client(max_attempts=3) as client:
            with pytest.raises(SolisAuthError):
                await client.inverter_list()
        assert len(respx.calls) == 1


class TestRateLimiter:
    def test_client_uses_the_documented_limit(self):
        """SolisCloud: "three times every five seconds for the same IP"."""
        assert (RATE_LIMIT_CALLS, RATE_LIMIT_PERIOD) == (3, 5.0)

    async def test_never_exceeds_the_window(self):
        limiter = _RateLimiter(max_calls=3, period=0.3)
        stamps: list[float] = []

        async def call():
            await limiter.acquire()
            stamps.append(time.monotonic())

        await asyncio.gather(*(call() for _ in range(9)))

        for i, start in enumerate(stamps):
            in_window = [t for t in stamps[i:] if t - start < 0.3]
            assert len(in_window) <= 3, f"{len(in_window)} calls within one 0.3s window"


class TestRetryBackoff:
    """Backing off less than the rate-limit window puts every retry inside it."""

    async def test_rate_limit_backoff_clears_the_window(self, monkeypatch):
        slept: list[float] = []

        async def fake_sleep(seconds: float) -> None:
            slept.append(seconds)

        monkeypatch.setattr("soliscloud_api.client.asyncio.sleep", fake_sleep)

        with respx.mock:
            respx.post(LIST_URL).mock(return_value=httpx.Response(429, text="too many requests"))
            async with _client(max_attempts=3) as client:
                with pytest.raises(SolisRateLimitError):
                    await client.inverter_list()

        assert len(slept) == 2
        assert all(s >= RATE_LIMIT_PERIOD for s in slept), (
            f"backoff {slept} is shorter than the {RATE_LIMIT_PERIOD}s window that caused the rejection"
        )

    async def test_retry_after_zero_is_honoured_not_treated_as_absent(self, monkeypatch):
        slept: list[float] = []

        async def fake_sleep(seconds: float) -> None:
            slept.append(seconds)

        monkeypatch.setattr("soliscloud_api.client.asyncio.sleep", fake_sleep)

        with respx.mock:
            respx.post(LIST_URL).mock(
                side_effect=[
                    httpx.Response(429, headers={"Retry-After": "0"}, text="slow down"),
                    httpx.Response(200, json=INVERTER_LIST_RESPONSE),
                ]
            )
            async with _client(max_attempts=3) as client:
                await client.inverter_list()

        assert slept and slept[0] < 1.0, f"Retry-After: 0 should not fall back to a default delay, got {slept}"

    async def test_transport_errors_keep_the_short_backoff(self, monkeypatch):
        slept: list[float] = []

        async def fake_sleep(seconds: float) -> None:
            slept.append(seconds)

        monkeypatch.setattr("soliscloud_api.client.asyncio.sleep", fake_sleep)

        with respx.mock:
            respx.post(LIST_URL).mock(
                side_effect=[httpx.Response(500, text="boom"), httpx.Response(200, json=INVERTER_LIST_RESPONSE)]
            )
            async with _client(max_attempts=3) as client:
                await client.inverter_list()

        assert slept and slept[0] < RATE_LIMIT_PERIOD
