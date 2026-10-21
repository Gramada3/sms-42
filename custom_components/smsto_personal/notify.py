"""Notify entity: notify.send_message → default number(s)."""
from __future__ import annotations

from homeassistant.components.notify import NotifyEntity, NotifyEntityFeature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import SmstoConfigEntry, async_send
from .entity import device_info


async def async_setup_entry(
    hass: HomeAssistant, entry: SmstoConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    async_add_entities([SmstoNotifyEntity(entry)])


class SmstoNotifyEntity(NotifyEntity):
    _attr_has_entity_name = True
    _attr_translation_key = "sms"
    _attr_supported_features = NotifyEntityFeature.TITLE

    def __init__(self, entry: SmstoConfigEntry) -> None:
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_notify"
        self._attr_device_info = device_info(entry)

    async def async_send_message(self, message: str, title: str | None = None) -> None:
        await async_send(self.hass, self._entry, message, title)
