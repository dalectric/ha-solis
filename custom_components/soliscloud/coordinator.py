"""Polling coordinator for SolisCloud."""

from __future__ import annotations

import logging
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .soliscloud_api.client import SolisCloudClient
from .soliscloud_api.errors import SolisAuthError, SolisError
from .soliscloud_api.models import InverterDetail

_LOGGER = logging.getLogger(__name__)


class SolisCoordinator(DataUpdateCoordinator[dict[str, InverterDetail]]):
    """Fetch every inverter's detail on each poll, keyed by serial number."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        client: SolisCloudClient,
        interval_minutes: int,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name="SolisCloud",
            # Passed explicitly: relying on the ContextVar is deprecated in HA 2026.x.
            config_entry=entry,
            update_interval=timedelta(minutes=interval_minutes),
        )
        self.client = client

    async def _async_update_data(self) -> dict[str, InverterDetail]:
        try:
            listing = await self.client.inverter_list()
            return {
                inverter.sn: await self.client.inverter_detail(inverter_id=inverter.id, inverter_sn=inverter.sn)
                for inverter in listing.records
            }
        except SolisAuthError as err:
            # Prompts a re-auth flow instead of retrying forever with bad credentials.
            raise ConfigEntryAuthFailed(str(err)) from err
        except SolisError as err:
            # str(err) carries the endpoint and the API's own code and message, so the
            # HA log says what actually went wrong rather than "no data".
            raise UpdateFailed(str(err)) from err
