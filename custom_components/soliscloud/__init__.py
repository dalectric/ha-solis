"""The SolisCloud integration."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.httpx_client import get_async_client

from .const import (
    CONF_KEY_ID,
    CONF_KEY_SECRET,
    CONF_SCAN_INTERVAL_MINUTES,
    CONF_SIGN_CONVENTION,
    CONF_URL,
    DEFAULT_SCAN_INTERVAL_MINUTES,
    DEFAULT_SIGN_CONVENTION,
    DEFAULT_TIMEOUT_SECONDS,
    DEFAULT_URL,
    DOMAIN,
)
from .coordinator import SolisCoordinator
from .soliscloud_api.client import SolisCloudClient
from .soliscloud_api.settings import Settings

PLATFORMS: list[Platform] = [Platform.SELECT, Platform.SENSOR]

type SolisConfigEntry = ConfigEntry[SolisCoordinator]


def build_client(hass: HomeAssistant, entry: ConfigEntry) -> SolisCloudClient:
    """Build a client from config-entry data rather than from the environment.

    Uses Home Assistant's shared httpx client. Constructing our own inside the event
    loop would load the CA bundle synchronously, which HA detects and reports as a
    blocking call.
    """
    settings = Settings(
        solis_id=entry.data[CONF_KEY_ID],
        solis_secret=entry.data[CONF_KEY_SECRET],
        solis_url=entry.data.get(CONF_URL, DEFAULT_URL),
        solis_timeout=DEFAULT_TIMEOUT_SECONDS,
    )
    return SolisCloudClient(settings=settings, client=get_async_client(hass))


async def async_setup_entry(hass: HomeAssistant, entry: SolisConfigEntry) -> bool:
    client = build_client(hass, entry)
    interval = entry.options.get(
        CONF_SCAN_INTERVAL_MINUTES,
        entry.data.get(CONF_SCAN_INTERVAL_MINUTES, DEFAULT_SCAN_INTERVAL_MINUTES),
    )
    convention = entry.options.get(
        CONF_SIGN_CONVENTION,
        entry.data.get(CONF_SIGN_CONVENTION, DEFAULT_SIGN_CONVENTION),
    )
    coordinator = SolisCoordinator(hass, entry, client, interval, convention)

    # Registered before anything can fail, so the client is released whether setup
    # succeeds, the first refresh raises, or platform setup raises.
    entry.async_on_unload(client.aclose)

    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = coordinator
    entry.async_on_unload(entry.add_update_listener(_async_reload_entry))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: SolisConfigEntry) -> bool:
    # The client is closed by the async_on_unload callback registered during setup.
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def _async_reload_entry(hass: HomeAssistant, entry: SolisConfigEntry) -> None:
    """Reload only when something that needs it changed.

    Flipping the sign convention is applied in place by the select entity, so
    reloading for it would re-poll a slow API for no reason.
    """
    coordinator = entry.runtime_data
    convention = entry.options.get(CONF_SIGN_CONVENTION, DEFAULT_SIGN_CONVENTION)
    interval_minutes = entry.options.get(CONF_SCAN_INTERVAL_MINUTES, DEFAULT_SCAN_INTERVAL_MINUTES)

    if (
        convention == coordinator.sign_convention
        and coordinator.update_interval is not None
        and interval_minutes == coordinator.update_interval.total_seconds() / 60
    ):
        return

    await hass.config_entries.async_reload(entry.entry_id)


__all__ = ["DOMAIN", "SolisConfigEntry", "async_setup_entry", "async_unload_entry"]
