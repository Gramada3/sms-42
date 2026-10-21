"""Diagnostics (secrets and phone numbers redacted)."""
from __future__ import annotations

from dataclasses import asdict
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from . import SmstoConfigEntry
from .const import CONF_API_KEY, CONF_DEFAULT_TARGET, CONF_WEBHOOK_ID, CONF_WEBHOOK_SECRET

REDACT = {CONF_API_KEY, CONF_DEFAULT_TARGET, CONF_WEBHOOK_ID, CONF_WEBHOOK_SECRET,
          "to", "phone", "recipients", "message", "raw"}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: SmstoConfigEntry
) -> dict[str, Any]:
    coordinator = entry.runtime_data.coordinator
    return {
        "entry": async_redact_data({**entry.data}, REDACT),
        "options": async_redact_data({**entry.options}, REDACT),
        "last_update_success": coordinator.last_update_success,
        "data": async_redact_data(asdict(coordinator.data), REDACT) if coordinator.data else None,
    }
