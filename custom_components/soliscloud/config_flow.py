"""Config flow for SolisCloud."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.httpx_client import get_async_client

from .const import (
    CONF_KEY_ID,
    CONF_KEY_SECRET,
    CONF_SCAN_INTERVAL_MINUTES,
    CONF_SIGN_CONVENTION,
    CONF_URL,
    CONFIG_FLOW_MAX_ATTEMPTS,
    CONFIG_FLOW_TIMEOUT_SECONDS,
    DEFAULT_SCAN_INTERVAL_MINUTES,
    DEFAULT_SIGN_CONVENTION,
    DEFAULT_URL,
    DOMAIN,
    MIN_SCAN_INTERVAL_MINUTES,
    SIGN_CONVENTIONS,
)
from .soliscloud_api.client import SolisCloudClient
from .soliscloud_api.errors import (
    SolisAPIError,
    SolisAuthError,
    SolisClockSkewError,
    SolisRateLimitError,
    SolisTransportError,
)
from .soliscloud_api.settings import Settings

STEP_USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_URL, default=DEFAULT_URL): str,
        vol.Required(CONF_KEY_ID): str,
        vol.Required(CONF_KEY_SECRET): str,
    }
)


async def _validate(hass: HomeAssistant, user_input: dict[str, Any]) -> tuple[str | None, int]:
    """Return (error_key, inverter_count). error_key is None on success.

    Deliberately one attempt on a short timeout: the dialog blocks until this returns,
    and the runtime defaults (60s x 3 retries) would leave it apparently frozen for
    over three minutes on an unreachable URL.
    """
    settings = Settings(
        solis_id=user_input[CONF_KEY_ID],
        solis_secret=user_input[CONF_KEY_SECRET],
        solis_url=user_input[CONF_URL],
        solis_timeout=CONFIG_FLOW_TIMEOUT_SECONDS,
    )
    client = SolisCloudClient(
        settings=settings,
        client=get_async_client(hass),
        max_attempts=CONFIG_FLOW_MAX_ATTEMPTS,
    )
    try:
        listing = await client.inverter_list()
    except SolisAuthError:
        return "invalid_auth", 0
    except SolisClockSkewError:
        return "clock_skew", 0
    except SolisRateLimitError:
        return "rate_limited", 0
    except SolisTransportError:
        return "cannot_connect", 0
    except SolisAPIError:
        return "api_error", 0
    finally:
        await client.aclose()
    if not listing.records:
        return "no_inverters", 0
    return None, len(listing.records)


class SolisCloudConfigFlow(ConfigFlow, domain=DOMAIN):
    """Each failure gets its own message, so a bad key never looks like an empty account."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            await self.async_set_unique_id(user_input[CONF_KEY_ID])
            self._abort_if_unique_id_configured()

            error, count = await _validate(self.hass, user_input)
            if error is None:
                return self.async_create_entry(
                    title=f"SolisCloud ({count} inverter{'s' if count != 1 else ''})",
                    data=user_input,
                )
            errors["base"] = error

        return self.async_show_form(step_id="user", data_schema=STEP_USER_SCHEMA, errors=errors)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry) -> SolisCloudOptionsFlow:
        return SolisCloudOptionsFlow()


class SolisCloudOptionsFlow(OptionsFlow):
    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data=user_input)

        options = self.config_entry.options
        interval = options.get(CONF_SCAN_INTERVAL_MINUTES, DEFAULT_SCAN_INTERVAL_MINUTES)
        convention = options.get(CONF_SIGN_CONVENTION, DEFAULT_SIGN_CONVENTION)
        schema = vol.Schema(
            {
                vol.Required(CONF_SCAN_INTERVAL_MINUTES, default=interval): vol.All(
                    int, vol.Range(min=MIN_SCAN_INTERVAL_MINUTES)
                ),
                # Also exposed as a select entity, so it can be flipped from a
                # dashboard without opening this dialog.
                vol.Required(CONF_SIGN_CONVENTION, default=convention): vol.In(SIGN_CONVENTIONS),
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)
