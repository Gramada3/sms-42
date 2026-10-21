"""Low-balance binary sensor."""
from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import SmstoConfigEntry, entry_option
from .const import CONF_LOW_BALANCE, DEFAULT_LOW_BALANCE
from .coordinator import SmstoCoordinator
from .entity import device_info


async def async_setup_entry(
    hass: HomeAssistant, entry: SmstoConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    async_add_entities([SmstoLowBalance(entry.runtime_data.coordinator, entry)])


class SmstoLowBalance(CoordinatorEntity[SmstoCoordinator], BinarySensorEntity):
    _attr_has_entity_name = True
    _attr_translation_key = "low_balance"
    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_icon = "mdi:cash-alert"

    def __init__(self, coordinator: SmstoCoordinator, entry: SmstoConfigEntry) -> None:
        super().__init__(coordinator)
        self._threshold = float(entry_option(entry, CONF_LOW_BALANCE, DEFAULT_LOW_BALANCE))
        self._attr_unique_id = f"{entry.entry_id}_low_balance"
        self._attr_device_info = device_info(entry)

    @property
    def is_on(self) -> bool | None:
        bal = self.coordinator.data.balance
        return None if bal is None else bal < self._threshold

    @property
    def extra_state_attributes(self):
        return {"threshold": self._threshold}
