"""SMS.to (personal) — SMS, flash SMS, Viber, contacts and delivery reports via SMS.to."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from homeassistant.components import webhook
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.network import NoURLAvailableError, get_url
from homeassistant.helpers.typing import ConfigType

from .api import CHANNEL_SMS, SmstoClient, SmstoError
from .const import (
    CONF_API_KEY,
    CONF_DEFAULT_TARGET,
    CONF_DELIVERY_REPORTS,
    CONF_SENDER_ID,
    CONF_TIMEZONE,
    CONF_WEBHOOK_ID,
    DOMAIN,
    EVENT_SENT,
)
from .coordinator import SmstoCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.SENSOR, Platform.BINARY_SENSOR, Platform.BUTTON, Platform.NOTIFY]
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


@dataclass
class SmstoRuntime:
    client: SmstoClient
    coordinator: SmstoCoordinator


type SmstoConfigEntry = ConfigEntry[SmstoRuntime]


def entry_option(entry: ConfigEntry, key: str, default: Any = "") -> Any:
    """Options override data (so most settings can be edited later)."""
    if key in entry.options and entry.options[key] not in (None, ""):
        return entry.options[key]
    val = entry.data.get(key, default)
    return default if val in (None, "") else val


def default_targets(entry: ConfigEntry) -> list[str]:
    raw = str(entry_option(entry, CONF_DEFAULT_TARGET, ""))
    return [t.strip() for t in raw.split(",") if t.strip()]


def webhook_url(hass: HomeAssistant, entry: ConfigEntry) -> str | None:
    """Public URL SMS.to should POST delivery reports to (None if unavailable)."""
    if not entry_option(entry, CONF_DELIVERY_REPORTS, False):
        return None
    wid = entry.data.get(CONF_WEBHOOK_ID)
    if not wid:
        return None
    try:
        base = get_url(hass, allow_internal=False, prefer_cloud=True)
    except NoURLAvailableError:
        _LOGGER.warning(
            "Delivery reports are enabled but Home Assistant has no external URL "
            "(set one, or use Nabu Casa); sending without callback_url"
        )
        return None
    return f"{base}{webhook.async_generate_path(wid)}"


async def async_send(
    hass: HomeAssistant,
    entry: SmstoConfigEntry,
    message: str,
    title: str | None = None,
    targets: list[str] | None = None,
    sender_id: str | None = None,
    *,
    channel: str = CHANNEL_SMS,
    scheduled_for: str | None = None,
    timezone: str | None = None,
    bypass_optout: bool | None = None,
    callback_url: str | None = None,
    estimate: bool = False,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Send (or estimate) one message to one or more numbers."""
    targets = [t.strip() for t in (targets or default_targets(entry)) if t and t.strip()]
    if not targets:
        raise ServiceValidationError(
            "No recipient: pass 'target' or set a default number in the integration options."
        )
    text = f"{title}\n\n{message}" if title else message
    try:
        result = await entry.runtime_data.client.send(
            text,
            targets,
            sender_id or entry_option(entry, CONF_SENDER_ID),
            channel=channel,
            callback_url=callback_url or webhook_url(hass, entry),
            scheduled_for=scheduled_for,
            timezone=timezone or (entry_option(entry, CONF_TIMEZONE) if scheduled_for else None),
            bypass_optout=bypass_optout,
            estimate=estimate,
            extra=extra,
        )
    except SmstoError as err:
        raise HomeAssistantError(f"SMS.to: {err}") from err
    if not estimate:
        hass.bus.async_fire(
            EVENT_SENT,
            {
                "config_entry_id": entry.entry_id,
                "channel": channel,
                "targets": targets,
                "scheduled_for": scheduled_for,
                "message_id": result.get("message_id"),
                "campaign_id": result.get("campaign_id"),
            },
        )
        await entry.runtime_data.coordinator.async_request_refresh()
    return result


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    from .services import async_register_services

    async_register_services(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: SmstoConfigEntry) -> bool:
    # Entries created by v1.0 have no webhook id/secret yet.
    if CONF_WEBHOOK_ID not in entry.data:
        hass.config_entries.async_update_entry(
            entry,
            data={
                **entry.data,
                CONF_WEBHOOK_ID: webhook.async_generate_id(),
            },
        )

    client = SmstoClient(async_get_clientsession(hass), entry.data[CONF_API_KEY])
    coordinator = SmstoCoordinator(hass, entry, client)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = SmstoRuntime(client, coordinator)

    from .webhook_handler import async_register_webhook

    async_register_webhook(hass, entry)
    entry.async_on_unload(lambda: webhook.async_unregister(hass, entry.data[CONF_WEBHOOK_ID]))

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_reload))
    return True


async def _async_reload(hass: HomeAssistant, entry: SmstoConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: SmstoConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
