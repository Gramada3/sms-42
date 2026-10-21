"""Refresh button."""
from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import SmstoConfigEntry
from .entity import device_info


async def async_setup_entry(
    hass: HomeAssistant, entry: SmstoConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    async_add_entities([SmstoRefreshButton(entry)])


class SmstoRefreshButton(ButtonEntity):
    _attr_has_entity_name = True
    _attr_translation_key = "refresh"
    _attr_icon = "mdi:refresh"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, entry: SmstoConfigEntry) -> None:
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_refresh"
        self._attr_device_info = device_info(entry)

    async def async_press(self) -> None:
        await self._entry.runtime_data.coordinator.async_request_refresh()
