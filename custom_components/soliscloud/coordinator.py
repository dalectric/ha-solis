"""Polling coordinator for SolisCloud."""

from __future__ import annotations

import logging
from collections import deque
from datetime import datetime, timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.update_coordinator import TimestampDataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .const import DOMAIN
from .soliscloud_api.client import SolisCloudClient
from .soliscloud_api.errors import SolisAuthError, SolisError
from .soliscloud_api.models import InverterDetail

_LOGGER = logging.getLogger(__name__)

# Failed polls older than this drop out of the failure count.
FAILURE_WINDOW = timedelta(hours=24)


def service_device_info(entry_id: str) -> DeviceInfo:
    """The account-level device that carries entities not tied to one inverter."""
    return DeviceInfo(
        identifiers={(DOMAIN, entry_id)},
        manufacturer="Solis",
        name="SolisCloud",
        entry_type=DeviceEntryType.SERVICE,
    )


class SolisCoordinator(TimestampDataUpdateCoordinator[dict[str, InverterDetail]]):
    """Fetch every inverter's detail on each poll, keyed by serial number.

    Tracks poll health as well: `last_update_success_time` (from the base class) and
    the time and error of every failed poll within FAILURE_WINDOW.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        client: SolisCloudClient,
        interval_minutes: int,
        sign_convention: str,
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
        # Held here rather than read from the entry on every state read, so the select
        # entity can flip it and push new states without reloading and re-polling.
        self.sign_convention = sign_convention
        self._failures: deque[datetime] = deque()
        self.last_failure_time: datetime | None = None
        self.last_failure_error: str | None = None

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

    @callback
    def _async_refresh_finished(self) -> None:
        super()._async_refresh_finished()
        if self.last_update_success:
            return
        self.last_failure_time = dt_util.utcnow()
        self.last_failure_error = str(self.last_exception) if self.last_exception else None
        self._failures.append(self.last_failure_time)
        # The base class skips listener updates on a second failure in a row, which
        # would freeze the failure count; push them here so it always moves.
        self.async_update_listeners()

    def failures_in_window(self, now: datetime | None = None) -> int:
        """Failed polls within FAILURE_WINDOW of `now`."""
        cutoff = (now or dt_util.utcnow()) - FAILURE_WINDOW
        while self._failures and self._failures[0] < cutoff:
            self._failures.popleft()
        return len(self._failures)
