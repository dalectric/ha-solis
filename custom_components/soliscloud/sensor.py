"""Sensor entities for SolisCloud.

Entities are generated from the table below: one tuple per sensor, keyed by the
attribute name on InverterDetail. Adding a sensor is a single line.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    PERCENTAGE,
    UnitOfElectricCurrent,
    UnitOfElectricPotential,
    UnitOfEnergy,
    UnitOfFrequency,
    UnitOfPower,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import SolisConfigEntry
from .const import DOMAIN, SIGN_CONVENTION_GENERATOR
from .coordinator import SolisCoordinator

_MEASURE = SensorStateClass.MEASUREMENT
_TOTAL = SensorStateClass.TOTAL_INCREASING


class Flow(StrEnum):
    """What a positive value means in the raw SolisCloud payload.

    SolisCloud mixes conventions: pac, psum and batteryPower are positive when the
    component delivers power, while familyLoadPower is positive when it consumes.
    Classifying each field lets the integration present one consistent system.
    """

    NONE = "none"
    """Unsigned magnitude -- voltage, current, frequency, SOC, temperature."""

    DELIVERS = "delivers"
    """Raw positive means power leaving the component (PV, export, discharge)."""

    CONSUMES = "consumes"
    """Raw positive means power entering the component (house load)."""


@dataclass(frozen=True, kw_only=True)
class SolisSensorDescription(SensorEntityDescription):
    flow: Flow = Flow.NONE


def sign_multiplier(flow: Flow, convention: str) -> int:
    """Factor converting a raw value into the chosen sign convention.

    https://en.wikipedia.org/wiki/Passive_sign_convention

    Cumulative energy counters are deliberately Flow.NONE. They are not signed
    quantities but two separate one-way meters (kWh imported, kWh exported), and
    Home Assistant's Energy dashboard requires total_increasing sensors to stay
    positive and monotonic.
    """
    if flow is Flow.NONE:
        return 1
    # Normalise to the generator convention first: positive means power produced.
    to_generator = 1 if flow is Flow.DELIVERS else -1
    return to_generator if convention == SIGN_CONVENTION_GENERATOR else -to_generator


def _power(key: str, name: str, flow: Flow = Flow.DELIVERS) -> SolisSensorDescription:
    return SolisSensorDescription(
        key=key,
        name=name,
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.WATT,
        state_class=_MEASURE,
        flow=flow,
    )


def _energy(key: str, name: str) -> SolisSensorDescription:
    return SolisSensorDescription(
        key=key,
        name=name,
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        state_class=_TOTAL,
    )


def _volts(key: str, name: str) -> SolisSensorDescription:
    return SolisSensorDescription(
        key=key,
        name=name,
        device_class=SensorDeviceClass.VOLTAGE,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        state_class=_MEASURE,
        entity_registry_enabled_default=False,
    )


def _amps(key: str, name: str) -> SolisSensorDescription:
    return SolisSensorDescription(
        key=key,
        name=name,
        device_class=SensorDeviceClass.CURRENT,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        state_class=_MEASURE,
        entity_registry_enabled_default=False,
    )


SENSORS: tuple[SolisSensorDescription, ...] = (
    # Power
    _power("pac", "PV power"),
    _power("p_sum", "Grid power"),
    _power("family_load_power", "House load", Flow.CONSUMES),
    _power("total_load_power", "Total load", Flow.CONSUMES),
    _power("battery_power", "Battery power"),
    _power("bypass_load_power", "Backup load", Flow.CONSUMES),
    _power("pow1", "String 1 power"),
    _power("pow2", "String 2 power"),
    _power("pow3", "String 3 power"),
    _power("pow4", "String 4 power"),
    # Generation energy
    _energy("e_today", "Generation today"),
    _energy("e_month", "Generation this month"),
    _energy("e_year", "Generation this year"),
    _energy("e_total", "Generation total"),
    # Grid energy
    _energy("grid_purchased_today_energy", "Grid import today"),
    _energy("grid_purchased_total_energy", "Grid import total"),
    _energy("grid_sell_today_energy", "Grid export today"),
    _energy("grid_sell_total_energy", "Grid export total"),
    _energy("home_load_today_energy", "House consumption today"),
    _energy("home_load_total_energy", "House consumption total"),
    # Battery energy
    _energy("battery_today_charge_energy", "Battery charged today"),
    _energy("battery_today_discharge_energy", "Battery discharged today"),
    _energy("battery_total_charge_energy", "Battery charged total"),
    _energy("battery_total_discharge_energy", "Battery discharged total"),
    # Battery state
    SolisSensorDescription(
        key="battery_capacity_soc",
        name="Battery",
        device_class=SensorDeviceClass.BATTERY,
        native_unit_of_measurement=PERCENTAGE,
        state_class=_MEASURE,
    ),
    SolisSensorDescription(
        key="battery_health_soh",
        name="Battery health",
        native_unit_of_measurement=PERCENTAGE,
        state_class=_MEASURE,
        entity_registry_enabled_default=False,
    ),
    _volts("battery_voltage", "Battery voltage"),
    _amps("battery_current", "Battery current"),
    # Inverter
    SolisSensorDescription(
        key="inverter_temperature",
        name="Inverter temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=_MEASURE,
    ),
    SolisSensorDescription(
        key="fac",
        name="Grid frequency",
        device_class=SensorDeviceClass.FREQUENCY,
        native_unit_of_measurement=UnitOfFrequency.HERTZ,
        state_class=_MEASURE,
        entity_registry_enabled_default=False,
    ),
    SolisSensorDescription(
        key="data_timestamp",
        name="Last reading",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_registry_enabled_default=False,
    ),
    # PV strings and AC phases, off by default to avoid flooding the entity list.
    _volts("u_pv1", "String 1 voltage"),
    _volts("u_pv2", "String 2 voltage"),
    _volts("u_pv3", "String 3 voltage"),
    _volts("u_pv4", "String 4 voltage"),
    _amps("i_pv1", "String 1 current"),
    _amps("i_pv2", "String 2 current"),
    _amps("i_pv3", "String 3 current"),
    _amps("i_pv4", "String 4 current"),
    _volts("u_ac1", "Phase 1 voltage"),
    _volts("u_ac2", "Phase 2 voltage"),
    _volts("u_ac3", "Phase 3 voltage"),
    _amps("i_ac1", "Phase 1 current"),
    _amps("i_ac2", "Phase 2 current"),
    _amps("i_ac3", "Phase 3 current"),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SolisConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    async_add_entities(
        SolisSensor(coordinator, serial, description) for serial in coordinator.data for description in SENSORS
    )


class SolisSensor(CoordinatorEntity[SolisCoordinator], SensorEntity):
    _attr_has_entity_name = True

    def __init__(self, coordinator: SolisCoordinator, serial: str, description: SolisSensorDescription) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._serial = serial
        self._attr_unique_id = f"{serial}_{description.key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, serial)},
            manufacturer="Solis",
            name=f"Solis {serial}",
            serial_number=serial,
        )

    @property
    def available(self) -> bool:
        return super().available and self._serial in self.coordinator.data

    @property
    def native_value(self):
        inverter = self.coordinator.data.get(self._serial)
        if inverter is None:
            return None
        # None propagates deliberately: a field the API omitted shows as `unknown`
        # rather than a plausible-looking zero.
        value = getattr(inverter, self.entity_description.key, None)
        if value is None:
            return None
        factor = sign_multiplier(self.entity_description.flow, self.coordinator.sign_convention)
        return value if factor == 1 else value * factor
