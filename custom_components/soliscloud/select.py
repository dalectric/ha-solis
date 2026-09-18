"""Sign convention selector.

Exposes which Zaehlpfeilsystem the power sensors currently use, and lets it be
changed from the UI. The entity's state is the indicator and the control at once.
"""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import SolisConfigEntry
from .const import (
    CONF_SIGN_CONVENTION,
    DOMAIN,
    SIGN_CONVENTION_CONSUMER,
    SIGN_CONVENTION_GENERATOR,
    SIGN_CONVENTIONS,
)
from .coordinator import SolisCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SolisConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    async_add_entities([SolisSignConventionSelect(entry.runtime_data, entry)])


class SolisSignConventionSelect(CoordinatorEntity[SolisCoordinator], SelectEntity):
    """Which Zaehlpfeilsystem the signed power sensors follow."""

    _attr_has_entity_name = True
    _attr_name = "Sign convention"
    _attr_icon = "mdi:plus-minus-variant"
    _attr_entity_category = None
    _attr_options = SIGN_CONVENTIONS
    _attr_translation_key = "sign_convention"

    def __init__(self, coordinator: SolisCoordinator, entry: SolisConfigEntry) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_sign_convention"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "manufacturer": "Solis",
            "name": "SolisCloud",
            "entry_type": "service",
        }

    @property
    def current_option(self) -> str:
        return self.coordinator.sign_convention

    @property
    def extra_state_attributes(self) -> dict[str, str]:
        generator = self.coordinator.sign_convention == SIGN_CONVENTION_GENERATOR
        return {
            "system": "Erzeugerzaehlpfeilsystem (EZS)" if generator else "Verbraucherzaehlpfeilsystem (VZS)",
            "positive_means": "power delivered" if generator else "power consumed",
            "grid_positive": "exporting" if generator else "importing",
            "battery_positive": "discharging" if generator else "charging",
            "pv_positive": "generating" if generator else "never (PV only delivers)",
            "note": (
                "Applies to signed power sensors. Cumulative energy counters are one-way "
                "meters and stay positive so the Energy dashboard keeps working."
            ),
            "reference": "https://de.wikipedia.org/wiki/Zaehlpfeil",
        }

    async def async_select_option(self, option: str) -> None:
        if option not in SIGN_CONVENTIONS:
            raise ValueError(f"unknown sign convention: {option!r}")
        if option == self.coordinator.sign_convention:
            return

        # Applied in place first so every sensor flips immediately; persisting to the
        # entry afterwards keeps it across restarts without forcing a reload and a
        # fresh poll of a slow API.
        self.coordinator.sign_convention = option
        self.hass.config_entries.async_update_entry(
            self._entry,
            options={**self._entry.options, CONF_SIGN_CONVENTION: option},
        )
        self.coordinator.async_update_listeners()


__all__ = ["SIGN_CONVENTION_CONSUMER", "SolisSignConventionSelect", "async_setup_entry"]
