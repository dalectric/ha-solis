from typing import ClassVar

from soliscloud_api.models import (
    InverterDetail,
    InverterInfo,
    InverterListResponse,
    PageInfo,
    SolisResponse,
)


class TestSolisResponse:
    def test_parse_success(self):
        data = {"success": True, "code": "0", "msg": "success", "data": {"key": "value"}}
        resp = SolisResponse.model_validate(data)
        assert resp.success is True
        assert resp.code == "0"
        assert resp.data == {"key": "value"}

    def test_parse_error(self):
        data = {"success": False, "code": "1001", "msg": "invalid params", "data": None}
        resp = SolisResponse.model_validate(data)
        assert resp.success is False
        assert resp.code == "1001"


class TestPageInfo:
    def test_parse_with_aliases(self):
        data = {"pageNo": 1, "pageSize": 20, "total": 42}
        page = PageInfo.model_validate(data)
        assert page.page_no == 1
        assert page.page_size == 20
        assert page.total == 42

    def test_parse_alternative_fields(self):
        data = {"current": 1, "pages": 1, "total": 2}
        page = PageInfo.model_validate(data)
        assert page.current == 1
        assert page.pages == 1
        assert page.total == 2


class TestInverterInfo:
    def test_parse_basic(self):
        data = {
            "id": "123",
            "sn": "INV001",
            "stationId": "ST001",
            "state": 1,
            "pac": 4.313,
            "etoday": 6.1,
            "etotal": 2.687,
            "batteryCapacitySoc": 99.0,
            "familyLoadPower": 0.368,
            "psum": 3.86,
        }
        inv = InverterInfo.model_validate(data)
        assert inv.id == "123"
        assert inv.sn == "INV001"
        assert inv.station_id == "ST001"
        assert inv.pac == 4.313
        assert inv.e_today == 6.1

    def test_absent_numerics_are_none_not_zero(self):
        """A field the API did not send must not read as a real zero.

        0.0 would publish a confident false reading to Home Assistant; None lets the
        entity go `unknown` instead.
        """
        data = {"id": "1", "sn": "X", "stationId": "S", "state": 0}
        inv = InverterInfo.model_validate(data)
        assert inv.pac is None
        assert inv.e_today is None
        assert inv.battery_capacity_soc is None

    def test_blank_string_is_none(self):
        data = {"id": "1", "sn": "X", "stationId": "S", "state": 0, "pac": ""}
        assert InverterInfo.model_validate(data).pac is None

    def test_extra_fields_allowed(self):
        data = {"id": "1", "sn": "X", "stationId": "S", "state": 0, "unknownField": "ok"}
        inv = InverterInfo.model_validate(data)
        assert inv.id == "1"


class TestInverterDetail:
    def test_battery_fields(self):
        data = {
            "id": "1",
            "sn": "X",
            "stationId": "S",
            "state": 1,
            "batteryCapacitySoc": 85.0,
            "batteryPower": -500.0,
            "familyLoadPower": 1200.0,
            "psum": -300.0,
        }
        detail = InverterDetail.model_validate(data)
        assert detail.battery_capacity_soc == 85.0
        assert detail.battery_power == -500.0
        assert detail.family_load_power == 1200.0
        assert detail.p_sum == -300.0


class TestInverterListResponse:
    def test_parse_full(self):
        data = {
            "inverterStatusVo": {"all": 2, "normal": 1, "fault": 0, "offline": 1},
            "page": {
                "current": 1,
                "pages": 1,
                "total": 2,
                "size": 100,
                "records": [
                    {"id": "1", "sn": "A", "stationId": "S1", "state": 1, "pac": 1000.0},
                    {"id": "2", "sn": "B", "stationId": "S1", "state": 0, "pac": 0.0},
                ],
            },
        }
        result = InverterListResponse.model_validate(data)
        assert result.inverter_status_vo.all == 2
        assert result.page.total == 2
        assert len(result.records) == 2
        assert result.records[0].sn == "A"


class TestUnitNormalisation:
    """Values are rescaled using the `<field>Str` companion.

    All figures below are taken from a real inverterDetail response. The point of this
    is that units differ *between fields in the same payload*: eToday arrives in kWh
    while eYear and eTotal arrive in MWh. Untouched, today's generation (10.3) would
    look larger than lifetime generation (7.341).
    """

    BASE: ClassVar[dict] = {"id": "1", "sn": "X", "stationId": "S", "state": 1}

    def _detail(self, **payload):
        return InverterDetail.model_validate(self.BASE | payload)

    def test_kw_power_becomes_watts(self):
        assert self._detail(pac=1.369, pacStr="kW").pac == 1369.0

    def test_watts_pass_through(self):
        assert self._detail(pac=1369.0, pacStr="W").pac == 1369.0

    def test_negative_power_keeps_sign(self):
        assert self._detail(batteryPower=-0.037, batteryPowerStr="kW").battery_power == -37.0

    def test_kwh_energy_passes_through(self):
        assert self._detail(eToday=10.3, eTodayStr="kWh").e_today == 10.3

    def test_mwh_energy_becomes_kwh(self):
        assert self._detail(eTotal=7.341, eTotalStr="MWh").e_total == 7341.0

    def test_gwh_energy_becomes_kwh(self):
        assert self._detail(eTotal=0.5, eTotalStr="GWh").e_total == 500000.0

    def test_mixed_units_in_one_payload_become_consistent(self):
        d = self._detail(
            eToday=10.3,
            eTodayStr="kWh",
            eMonth=291.4,
            eMonthStr="kWh",
            eYear=5.414,
            eYearStr="MWh",
            eTotal=7.341,
            eTotalStr="MWh",
        )
        assert (d.e_today, d.e_month, d.e_year, d.e_total) == (10.3, 291.4, 5414.0, 7341.0)
        assert d.e_today <= d.e_month <= d.e_year <= d.e_total

    def test_unknown_unit_passes_through_untouched(self):
        assert self._detail(pac=7.0, pacStr="furlongs").pac == 7.0

    def test_missing_unit_leaves_value_alone(self):
        assert self._detail(pac=2.5).pac == 2.5

    def test_non_string_unit_is_ignored(self):
        assert self._detail(pac=2.5, pacStr=None).pac == 2.5

    def test_lowercase_alias_also_normalised(self):
        assert self._detail(etotal=7.341, etotalStr="MWh").e_total == 7341.0


class TestRealPayloadShape:
    """Shapes taken from the live API, so regressions in aliasing get caught."""

    def test_timestamp_is_parsed_from_epoch_millis(self):
        data = {"id": "1", "sn": "X", "stationId": "S", "state": 1, "dataTimestamp": 1789642375879.0}
        ts = InverterDetail.model_validate(data).data_timestamp
        assert ts is not None and ts.year == 2026 and ts.tzinfo is not None

    def test_unmapped_fields_are_retained(self):
        data = {"id": "1", "sn": "X", "stationId": "S", "state": 1, "sscCurrentFlowMap": {"a": 1}}
        detail = InverterDetail.model_validate(data)
        assert (detail.model_extra or {})["sscCurrentFlowMap"] == {"a": 1}


class TestStringNumericsCoerced:
    def test_pv_and_ac_strings_become_floats(self):
        data = {
            "id": "1",
            "sn": "X",
            "stationId": "S",
            "state": 1,
            "uPv1": "330.5",
            "iPv1": "8.2",
            "uAc1": "230.5",
            "iAc1": "10.8",
        }
        detail = InverterDetail.model_validate(data)
        assert detail.u_pv1 == 330.5
        assert detail.i_pv1 == 8.2
        assert detail.u_ac1 == 230.5
        assert detail.i_ac1 == 10.8
