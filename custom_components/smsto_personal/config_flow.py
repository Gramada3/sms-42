"""Config flow: validates the API key by reading the balance (no SMS spent)."""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ._compat import vol

from homeassistant.components import webhook
from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.core import callback
from homeassistant.helpers import selector
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.network import NoURLAvailableError, get_url

from .api import SmstoAuthError, SmstoClient, SmstoError
from .const import (
    CONF_API_KEY,
    CONF_DEFAULT_TARGET,
    CONF_DELIVERY_REPORTS,
    CONF_LOW_BALANCE,
    CONF_SCAN_INTERVAL,
    CONF_SENDER_ID,
    CONF_TIMEZONE,
    CONF_WEBHOOK_ID,
    CONF_WEBHOOK_SECRET,
    DEFAULT_LOW_BALANCE,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
)


async def _validate(hass, api_key: str) -> str | None:
    try:
        await SmstoClient(async_get_clientsession(hass), api_key).get_balance()
    except SmstoAuthError:
        return "invalid_auth"
    except SmstoError:
        return "cannot_connect"
    return None


def _sender_ok(sender_id: str) -> bool:
    numeric = sender_id.lstrip("+").isdigit()
    return bool(sender_id) and len(sender_id) <= (16 if numeric else 11)


class SmstoPersonalConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            api_key = user_input[CONF_API_KEY].strip()
            sender_id = user_input[CONF_SENDER_ID].strip()
            if not _sender_ok(sender_id):
                errors[CONF_SENDER_ID] = "invalid_sender_id"
            elif (err := await _validate(self.hass, api_key)) is not None:
                errors["base"] = err
            else:
                await self.async_set_unique_id(api_key[-8:])
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=f"SMS.to ({sender_id})",
                    data={
                        CONF_API_KEY: api_key,
                        CONF_SENDER_ID: sender_id,
                        CONF_DEFAULT_TARGET: user_input.get(CONF_DEFAULT_TARGET, "").strip(),
                        CONF_WEBHOOK_ID: webhook.async_generate_id(),
                    },
                )

        schema = vol.Schema(
            {
                vol.Required(CONF_API_KEY): selector.TextSelector(
                    selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)
                ),
                vol.Required(CONF_SENDER_ID): str,
                vol.Optional(CONF_DEFAULT_TARGET, default=""): str,
            }
        )
        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(schema, user_input or {}),
            errors=errors,
        )

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            api_key = user_input[CONF_API_KEY].strip()
            if (err := await _validate(self.hass, api_key)) is None:
                return self.async_update_reload_and_abort(
                    self._get_reauth_entry(), data_updates={CONF_API_KEY: api_key}
                )
            errors["base"] = err
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({vol.Required(CONF_API_KEY): str}),
            errors=errors,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Change the API key without deleting the integration."""
        errors: dict[str, str] = {}
        if user_input is not None:
            api_key = user_input[CONF_API_KEY].strip()
            if (err := await _validate(self.hass, api_key)) is None:
                return self.async_update_reload_and_abort(
                    self._get_reconfigure_entry(), data_updates={CONF_API_KEY: api_key}
                )
            errors["base"] = err
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=vol.Schema({vol.Required(CONF_API_KEY): str}),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return SmstoOptionsFlow()


class SmstoOptionsFlow(OptionsFlow):
    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            if not _sender_ok(user_input[CONF_SENDER_ID].strip()):
                errors[CONF_SENDER_ID] = "invalid_sender_id"
            else:
                return self.async_create_entry(
                    data={k: v.strip() if isinstance(v, str) else v for k, v in user_input.items()}
                )

        cur = {**self.config_entry.data, **self.config_entry.options}
        try:
            base = get_url(self.hass, allow_internal=False, prefer_cloud=True)
            url = base + webhook.async_generate_path(self.config_entry.data.get(CONF_WEBHOOK_ID, ""))
        except NoURLAvailableError:
            url = "— (Home Assistant has no external URL)"

        schema = vol.Schema(
            {
                vol.Required(CONF_SENDER_ID, default=cur.get(CONF_SENDER_ID, "")): str,
                vol.Optional(CONF_DEFAULT_TARGET, default=cur.get(CONF_DEFAULT_TARGET, "")): str,
                vol.Optional(
                    CONF_LOW_BALANCE, default=float(cur.get(CONF_LOW_BALANCE, DEFAULT_LOW_BALANCE))
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=0, max=1000, step=0.5, mode=selector.NumberSelectorMode.BOX)
                ),
                vol.Optional(
                    CONF_SCAN_INTERVAL, default=int(cur.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL))
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=1, max=1440, step=1, unit_of_measurement="min",
                                                  mode=selector.NumberSelectorMode.BOX)
                ),
                vol.Optional(
                    CONF_TIMEZONE, default=cur.get(CONF_TIMEZONE) or self.hass.config.time_zone
                ): str,
                vol.Optional(
                    CONF_DELIVERY_REPORTS, default=bool(cur.get(CONF_DELIVERY_REPORTS, False))
                ): bool,
                vol.Optional(CONF_WEBHOOK_SECRET, default=cur.get(CONF_WEBHOOK_SECRET, "")): str,
            }
        )
        return self.async_show_form(
            step_id="init",
            data_schema=schema,
            errors=errors,
            description_placeholders={"webhook_url": url},
        )
