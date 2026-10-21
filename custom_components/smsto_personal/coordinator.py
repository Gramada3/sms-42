"""Polls balance, totals, last message and last campaign."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import SmstoAuthError, SmstoClient, SmstoError
from .const import CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL, DOMAIN

_LOGGER = logging.getLogger(__name__)


def unwrap(obj: Any) -> dict[str, Any]:
    """SMS.to sometimes nests the record under 'data' (dict or 1-item list)."""
    if isinstance(obj, dict) and "data" in obj and len(obj) <= 3:
        obj = obj["data"]
    if isinstance(obj, list):
        obj = obj[0] if obj else {}
    return obj if isinstance(obj, dict) else {}


@dataclass
class SmstoData:
    balance: float | None = None
    currency: str | None = None
    total_messages: int | None = None
    last_message: dict[str, Any] = field(default_factory=dict)
    last_campaign: dict[str, Any] = field(default_factory=dict)
    last_delivery: dict[str, Any] = field(default_factory=dict)


class SmstoCoordinator(DataUpdateCoordinator[SmstoData]):
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, client: SmstoClient) -> None:
        minutes = int(entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL))
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=timedelta(minutes=max(1, minutes)),
        )
        self.client = client

    async def _optional(self, coro, fallback):
        try:
            return await coro
        except SmstoAuthError:
            raise
        except SmstoError as err:
            _LOGGER.debug("Optional SMS.to call failed: %s", err)
            return fallback

    async def _async_update_data(self) -> SmstoData:
        prev = self.data or SmstoData()
        data = SmstoData(last_delivery=prev.last_delivery)
        try:
            data.balance, data.currency = await self.client.get_balance()
            data.total_messages = await self._optional(
                self.client.get_total_messages(), prev.total_messages
            )
            data.last_message = unwrap(
                await self._optional(self.client.get_last_message(), prev.last_message)
            )
            data.last_campaign = unwrap(
                await self._optional(self.client.get_last_campaign(), prev.last_campaign)
            )
        except SmstoAuthError as err:
            raise ConfigEntryAuthFailed("SMS.to API key rejected") from err
        except SmstoError as err:
            raise UpdateFailed(str(err)) from err
        return data
