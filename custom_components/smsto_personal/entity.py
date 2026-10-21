"""Shared device info."""
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo

from .const import CONF_SENDER_ID, DOMAIN


def device_info(entry: ConfigEntry) -> DeviceInfo:
    return DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id)},
        name=f"SMS.to ({entry.data.get(CONF_SENDER_ID, '')})",
        manufacturer="SMS.to",
        model="SMS gateway",
        entry_type=DeviceEntryType.SERVICE,
        configuration_url="https://sms.to/app",
    )
