import httpx
import respx

from forecast_solar.client import ForecastSolarClient
from forecast_solar.models import ForecastResult, PVArray, PVSite

SITE = PVSite(
    latitude=51.5,
    longitude=-0.12,
    arrays=[
        PVArray(name="South", decline=40, azimuth=0, kwp=0.445, modules=12),
        PVArray(name="East", decline=40, azimuth=-90, kwp=0.445, modules=4),
    ],
)

SAMPLE_RESPONSE = {
    "result": {
        "watts": {"2026-03-21 08:00:00": 200, "2026-03-21 09:00:00": 500},
        "watt_hours_period": {"2026-03-21 08:00:00": 100, "2026-03-21 09:00:00": 350},
        "watt_hours": {"2026-03-21 08:00:00": 100, "2026-03-21 09:00:00": 450},
        "watt_hours_day": {"2026-03-21": 4500},
    },
    "message": {"code": 0, "type": "success"},
}


class TestPVArray:
    def test_nominal_capacity(self):
        array = PVArray(name="Test", decline=40, azimuth=0, kwp=0.445, modules=12)
        assert array.nominal_capacity == 0.445 * 12


class TestPVSite:
    def test_multiple_arrays(self):
        assert len(SITE.arrays) == 2
        assert SITE.arrays[0].name == "South"
        assert SITE.arrays[1].name == "East"


class TestForecastResult:
    def test_parse(self):
        result = ForecastResult(array_name="South", **SAMPLE_RESPONSE["result"])
        assert result.array_name == "South"
        assert result.watt_hours_day == {"2026-03-21": 4500}
        assert len(result.watts) == 2


class TestForecastSolarClient:
    @respx.mock
    def test_estimate_no_cache(self):
        array = SITE.arrays[0]
        url = (
            f"https://api.forecast.solar/estimate"
            f"/{SITE.latitude}/{SITE.longitude}"
            f"/{array.decline}/{array.azimuth}/{array.nominal_capacity}"
        )
        respx.get(url).mock(return_value=httpx.Response(200, json=SAMPLE_RESPONSE))

        with ForecastSolarClient(SITE, cache_dir=None) as client:
            result = client.estimate(array)

        assert result.array_name == "South"
        assert result.watt_hours_day["2026-03-21"] == 4500

    @respx.mock
    def test_estimate_all(self):
        for array in SITE.arrays:
            url = (
                f"https://api.forecast.solar/estimate"
                f"/{SITE.latitude}/{SITE.longitude}"
                f"/{array.decline}/{array.azimuth}/{array.nominal_capacity}"
            )
            respx.get(url).mock(return_value=httpx.Response(200, json=SAMPLE_RESPONSE))

        with ForecastSolarClient(SITE, cache_dir=None) as client:
            results = client.estimate_all()

        assert len(results) == 2
        assert results[0].array_name == "South"
        assert results[1].array_name == "East"

    @respx.mock
    def test_cache_saves_and_serves(self, tmp_path):
        array = SITE.arrays[0]
        url = (
            f"https://api.forecast.solar/estimate"
            f"/{SITE.latitude}/{SITE.longitude}"
            f"/{array.decline}/{array.azimuth}/{array.nominal_capacity}"
        )
        respx.get(url).mock(return_value=httpx.Response(200, json=SAMPLE_RESPONSE))

        with ForecastSolarClient(SITE, cache_dir=tmp_path) as client:
            # First call: hits API and writes cache
            result1 = client.estimate(array)
            assert result1.watt_hours_day["2026-03-21"] == 4500

            cache_file = tmp_path / "forecast_solar_South.json"
            assert cache_file.exists()

            # Second call: served from cache (API would fail)
            respx.get(url).mock(side_effect=httpx.TimeoutException("should not be called"))
            result2 = client.estimate(array)
            assert result2.watt_hours_day["2026-03-21"] == 4500

    @respx.mock
    def test_cache_expires(self, tmp_path):

        array = SITE.arrays[0]
        url = (
            f"https://api.forecast.solar/estimate"
            f"/{SITE.latitude}/{SITE.longitude}"
            f"/{array.decline}/{array.azimuth}/{array.nominal_capacity}"
        )
        respx.get(url).mock(return_value=httpx.Response(200, json=SAMPLE_RESPONSE))

        with ForecastSolarClient(SITE, cache_dir=tmp_path, cache_ttl=0) as client:
            # First call writes cache
            client.estimate(array)

            # With ttl=0, cache is immediately stale — should hit API again
            result = client.estimate(array)
            assert result.watt_hours_day["2026-03-21"] == 4500
            assert len(respx.calls) == 2

    @respx.mock
    def test_estimate_aggregated(self):
        for array in SITE.arrays:
            url = (
                f"https://api.forecast.solar/estimate"
                f"/{SITE.latitude}/{SITE.longitude}"
                f"/{array.decline}/{array.azimuth}/{array.nominal_capacity}"
            )
            respx.get(url).mock(return_value=httpx.Response(200, json=SAMPLE_RESPONSE))

        with ForecastSolarClient(SITE, cache_dir=None) as client:
            total = client.estimate_aggregated()

        assert total.array_name == "Total"
        # Each array returns 4500 for the day, so total = 9000
        assert total.watt_hours_day["2026-03-21"] == 9000
        # Each array returns 200 watts at 08:00, so total = 400
        assert total.watts["2026-03-21 08:00:00"] == 400

    @respx.mock
    def test_check(self):
        check_url = f"https://api.forecast.solar/check/{SITE.latitude}/{SITE.longitude}"
        check_response = {"result": {"place": "Cork, Ireland"}}
        respx.get(check_url).mock(return_value=httpx.Response(200, json=check_response))

        with ForecastSolarClient(SITE) as client:
            result = client.check()

        assert result["result"]["place"] == "Cork, Ireland"
