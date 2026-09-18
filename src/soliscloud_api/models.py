"""Pydantic models for SolisCloud responses.

Two behaviours here are driven by what the API actually sends, verified against a real
``inverterDetail`` response (see ``data/raw/`` via ``python -m soliscloud_api dump``):

* **Numerics default to ``None``, never ``0.0``.** SolisCloud omits fields that do not
  apply to a given inverter, and a ``0.0`` default makes "not reported" indistinguishable
  from "currently zero" -- which publishes a confident false reading downstream.

* **Units are normalised on the way in.** Each numeric has a ``<field>Str`` companion
  naming its unit, and the unit differs *between fields in the same response*: one real
  payload carried ``eToday=10.3`` (kWh) alongside ``eTotal=7.341`` (MWh) and
  ``pac=1.369`` (kW). Taken at face value, today's generation would exceed lifetime
  generation. Power is converted to W and energy to kWh so every field shares one scale.

``extra="allow"`` is kept throughout: a real ``inverterDetail`` response has ~812 keys,
so the ~50 named below are the ones worth typing and the rest stay reachable through
``model_extra`` -- everything is fetched, nothing needs a schema change when Solis adds
a field.
"""

import contextlib
from datetime import UTC, datetime
from typing import Annotated, Any

from pydantic import AliasChoices, BaseModel, BeforeValidator, ConfigDict, Field, model_validator

# Power normalises to W, energy to kWh. The unit string itself says which is which.
_POWER_TO_W = {"w": 1.0, "kw": 1e3, "mw": 1e6, "gw": 1e9}
_ENERGY_TO_KWH = {"wh": 1e-3, "kwh": 1.0, "mwh": 1e3, "gwh": 1e6}

UNIT_SUFFIX = "Str"


def _blank_to_none(value: Any) -> Any:
    """Treat "" as absent. Several numeric fields arrive as empty strings."""
    if value == "" or value is None:
        return None
    return value


def _epoch_ms_to_datetime(value: Any) -> Any:
    """SolisCloud sends dataTimestamp as epoch milliseconds, typed as a number."""
    if value is None or value == "":
        return None
    if isinstance(value, int | float):
        return datetime.fromtimestamp(float(value) / 1000, tz=UTC)
    if isinstance(value, str) and value.isdigit():
        return datetime.fromtimestamp(float(value) / 1000, tz=UTC)
    return value


OptFloat = Annotated[float | None, BeforeValidator(_blank_to_none)]
OptInt = Annotated[int | None, BeforeValidator(_blank_to_none)]
OptStr = Annotated[str | None, BeforeValidator(_blank_to_none)]
OptDateTime = Annotated[datetime | None, BeforeValidator(_epoch_ms_to_datetime)]


def normalise_unit(value: float, unit: str) -> float:
    """Scale ``value`` to W (power) or kWh (energy). Unknown units pass through."""
    key = unit.strip().lower()
    if key in _POWER_TO_W:
        return value * _POWER_TO_W[key]
    if key in _ENERGY_TO_KWH:
        return value * _ENERGY_TO_KWH[key]
    return value


def _aliases_for(name: str, field: Any) -> list[str]:
    """Every payload key a field may be populated from."""
    validation_alias = field.validation_alias
    if isinstance(validation_alias, AliasChoices):
        return [str(choice) for choice in validation_alias.choices]
    if isinstance(validation_alias, str):
        return [validation_alias]
    return [field.alias or name]


class SolisModel(BaseModel):
    """Base with alias support, retention of unmapped fields, and unit normalisation."""

    model_config = ConfigDict(populate_by_name=True, extra="allow")

    @model_validator(mode="before")
    @classmethod
    def _normalise_units(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        out = dict(data)
        for name, field in cls.model_fields.items():
            for alias in _aliases_for(name, field):
                raw = data.get(alias)
                unit = data.get(f"{alias}{UNIT_SUFFIX}")
                if raw is None or raw == "" or not isinstance(unit, str):
                    continue
                with contextlib.suppress(TypeError, ValueError):
                    out[alias] = normalise_unit(float(raw), unit)
                break
        return out


class SolisResponse(BaseModel):
    success: bool
    code: str
    msg: str = ""
    data: Any = None


class PageInfo(SolisModel):
    page_no: OptInt = Field(None, alias="pageNo")
    page_size: OptInt = Field(None, alias="pageSize")
    total: int = 0
    current: int = 0
    pages: int = 0
    size: int = 0


class InverterStatusVo(SolisModel):
    all: int = 0
    normal: int = 0
    fault: int = 0
    offline: int = 0


class _InverterCommon(SolisModel):
    """Fields shared by the list records and the detail payload."""

    id: str
    sn: str
    station_id: OptStr = Field(None, alias="stationId")
    state: OptInt = None

    # Instantaneous power, W after normalisation.
    pac: OptFloat = None
    battery_power: OptFloat = Field(None, alias="batteryPower")
    family_load_power: OptFloat = Field(None, alias="familyLoadPower")
    total_load_power: OptFloat = Field(None, alias="totalLoadPower")
    p_sum: OptFloat = Field(None, alias="psum")

    # Energy, kWh after normalisation. Case varies by endpoint, so accept both.
    e_today: OptFloat = Field(None, validation_alias=AliasChoices("eToday", "etoday"))
    e_month: OptFloat = Field(None, validation_alias=AliasChoices("eMonth", "emonth"))
    e_year: OptFloat = Field(None, validation_alias=AliasChoices("eYear", "eyear"))
    e_total: OptFloat = Field(None, validation_alias=AliasChoices("eTotal", "etotal"))

    grid_purchased_today_energy: OptFloat = Field(None, alias="gridPurchasedTodayEnergy")
    grid_purchased_total_energy: OptFloat = Field(None, alias="gridPurchasedTotalEnergy")
    grid_sell_today_energy: OptFloat = Field(None, alias="gridSellTodayEnergy")
    grid_sell_total_energy: OptFloat = Field(None, alias="gridSellTotalEnergy")
    home_load_today_energy: OptFloat = Field(None, alias="homeLoadTodayEnergy")
    home_load_total_energy: OptFloat = Field(None, alias="homeLoadTotalEnergy")

    # Battery
    battery_capacity_soc: OptFloat = Field(None, alias="batteryCapacitySoc")
    battery_health_soh: OptFloat = Field(None, alias="batteryHealthSoh")
    battery_today_charge_energy: OptFloat = Field(None, alias="batteryTodayChargeEnergy")
    battery_today_discharge_energy: OptFloat = Field(None, alias="batteryTodayDischargeEnergy")
    battery_total_charge_energy: OptFloat = Field(None, alias="batteryTotalChargeEnergy")
    battery_total_discharge_energy: OptFloat = Field(None, alias="batteryTotalDischargeEnergy")


class InverterInfo(_InverterCommon):
    """One record from /v1/api/inverterList."""


class InverterDetail(_InverterCommon):
    """Payload from /v1/api/inverterDetail."""

    collector_id: OptStr = Field(None, alias="collectorId")
    data_timestamp: OptDateTime = Field(None, alias="dataTimestamp")
    inverter_temperature: OptFloat = Field(None, alias="inverterTemperature")

    # PV strings. Typed as floats -- the API sends several of these as strings.
    u_pv1: OptFloat = Field(None, alias="uPv1")
    u_pv2: OptFloat = Field(None, alias="uPv2")
    u_pv3: OptFloat = Field(None, alias="uPv3")
    u_pv4: OptFloat = Field(None, alias="uPv4")
    i_pv1: OptFloat = Field(None, alias="iPv1")
    i_pv2: OptFloat = Field(None, alias="iPv2")
    i_pv3: OptFloat = Field(None, alias="iPv3")
    i_pv4: OptFloat = Field(None, alias="iPv4")
    pow1: OptFloat = None
    pow2: OptFloat = None
    pow3: OptFloat = None
    pow4: OptFloat = None

    # AC phases
    u_ac1: OptFloat = Field(None, alias="uAc1")
    u_ac2: OptFloat = Field(None, alias="uAc2")
    u_ac3: OptFloat = Field(None, alias="uAc3")
    i_ac1: OptFloat = Field(None, alias="iAc1")
    i_ac2: OptFloat = Field(None, alias="iAc2")
    i_ac3: OptFloat = Field(None, alias="iAc3")
    fac: OptFloat = None

    # Battery electrical
    battery_voltage: OptFloat = Field(None, alias="storageBatteryVoltage")
    battery_current: OptFloat = Field(None, alias="storageBatteryCurrent")

    bypass_load_power: OptFloat = Field(None, alias="bypassLoadPower")
    soc_charging_set: OptFloat = Field(None, alias="socChargingSet")
    soc_discharge_set: OptFloat = Field(None, alias="socDischargeSet")


class InverterPage(PageInfo):
    records: list[InverterInfo] = Field(default_factory=list)


class InverterListResponse(SolisModel):
    inverter_status_vo: InverterStatusVo = Field(default_factory=InverterStatusVo, alias="inverterStatusVo")
    page: InverterPage

    @property
    def records(self) -> list[InverterInfo]:
        return self.page.records
