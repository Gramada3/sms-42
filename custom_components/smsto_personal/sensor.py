"""Sensors: balance, totals, last message, last campaign, last delivery report."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from . import SmstoConfigEntry
from .const import SIGNAL_DELIVERY
from .coordinator import SmstoCoordinator, SmstoData
from .entity import device_info


def _num(v: Any) -> float | None:
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def _ts(v: Any):
    if not v:
        return None
    if isinstance(v, (int, float)):
        return dt_util.utc_from_timestamp(v)
    parsed = dt_util.parse_datetime(str(v))
    if parsed and parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt_util.UTC)
    return parsed


def _first(d: dict, *keys: str) -> Any:
    for k in keys:
        if d.get(k) not in (None, ""):
            return d[k]
    return None


MSG_ATTRS = ("_id", "id", "to", "sender_id", "status", "cost", "sms_count", "parts",
             "created_at", "sent_at", "updated_at", "campaign_id", "type")
CAMP_ATTRS = ("_id", "id", "status", "sender_id", "estimated_cost", "price", "cost",
              "recipients", "sms_count", "created_at", "scheduled_for", "type")


@dataclass(frozen=True, kw_only=True)
class SmstoSensorDescription(SensorEntityDescription):
    value_fn: Callable[[SmstoData], Any]
    attrs_fn: Callable[[SmstoData], dict[str, Any]] | None = None
    unit_from_currency: bool = False


SENSORS: tuple[SmstoSensorDescription, ...] = (
    SmstoSensorDescription(
        key="balance",
        translation_key="balance",
        icon="mdi:cash",
        device_class=SensorDeviceClass.MONETARY,
        state_class=SensorStateClass.TOTAL,
        suggested_display_precision=2,
        unit_from_currency=True,
        value_fn=lambda d: d.balance,
    ),
    SmstoSensorDescription(
        key="total_messages",
        translation_key="total_messages",
        icon="mdi:message-text-outline",
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda d: d.total_messages,
    ),
    SmstoSensorDescription(
        key="last_message_status",
        translation_key="last_message_status",
        icon="mdi:message-check-outline",
        value_fn=lambda d: _first(d.last_message, "status"),
        attrs_fn=lambda d: {k: d.last_message[k] for k in MSG_ATTRS if k in d.last_message},
    ),
    SmstoSensorDescription(
        key="last_message_cost",
        translation_key="last_message_cost",
        icon="mdi:cash-minus",
        device_class=SensorDeviceClass.MONETARY,
        suggested_display_precision=4,
        unit_from_currency=True,
        value_fn=lambda d: _num(_first(d.last_message, "cost", "price")),
    ),
    SmstoSensorDescription(
        key="last_message_time",
        translation_key="last_message_time",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: _ts(_first(d.last_message, "sent_at", "created_at")),
    ),
    SmstoSensorDescription(
        key="last_campaign_status",
        translation_key="last_campaign_status",
        icon="mdi:bullhorn-outline",
        value_fn=lambda d: _first(d.last_campaign, "status"),
        attrs_fn=lambda d: {k: d.last_campaign[k] for k in CAMP_ATTRS if k in d.last_campaign},
    ),
    SmstoSensorDescription(
        key="last_campaign_cost",
        translation_key="last_campaign_cost",
        icon="mdi:cash-multiple",
        device_class=SensorDeviceClass.MONETARY,
        suggested_display_precision=4,
        unit_from_currency=True,
        value_fn=lambda d: _num(_first(d.last_campaign, "price", "cost", "estimated_cost")),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: SmstoConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator = entry.runtime_data.coordinator
    async_add_entities(
        [SmstoSensor(coordinator, entry, d) for d in SENSORS]
        + [SmstoDeliverySensor(coordinator, entry)]
    )


class SmstoSensor(CoordinatorEntity[SmstoCoordinator], SensorEntity):
    _attr_has_entity_name = True
    entity_description: SmstoSensorDescription

    def __init__(self, coordinator, entry, description) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"
        self._attr_device_info = device_info(entry)

    @property
    def native_value(self):
        return self.entity_description.value_fn(self.coordinator.data)

    @property
    def native_unit_of_measurement(self) -> str | None:
        if self.entity_description.unit_from_currency:
            return self.coordinator.data.currency or "EUR"
        return self.entity_description.native_unit_of_measurement

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        fn = self.entity_description.attrs_fn
        return fn(self.coordinator.data) if fn else None


class SmstoDeliverySensor(CoordinatorEntity[SmstoCoordinator], SensorEntity):
    """Last delivery report received on the webhook."""

    _attr_has_entity_name = True
    _attr_translation_key = "last_delivery_status"
    _attr_icon = "mdi:message-badge-outline"

    def __init__(self, coordinator: SmstoCoordinator, entry: SmstoConfigEntry) -> None:
        super().__init__(coordinator)
        self._entry_id = entry.entry_id
        self._attr_unique_id = f"{entry.entry_id}_last_delivery_status"
        self._attr_device_info = device_info(entry)

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, SIGNAL_DELIVERY.format(self._entry_id), self._on_report
            )
        )

    @callback
    def _on_report(self, report: dict[str, Any]) -> None:
        self.coordinator.data.last_delivery = report
        self.async_write_ha_state()

    @property
    def native_value(self):
        return self.coordinator.data.last_delivery.get("status")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        r = self.coordinator.data.last_delivery
        return {k: r.get(k) for k in ("message_id", "tracking_id", "phone", "cost", "parts", "received_at")}
