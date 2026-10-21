"""Receives SMS.to delivery reports (callback_url) and turns them into HA events."""
from __future__ import annotations

import json
import logging
from urllib.parse import parse_qsl

from aiohttp import web

from homeassistant.components import webhook
from homeassistant.core import HomeAssistant
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.util import dt as dt_util

from .api import verify_signature
from .const import CONF_WEBHOOK_ID, CONF_WEBHOOK_SECRET, DOMAIN, EVENT_DELIVERY, SIGNAL_DELIVERY

_LOGGER = logging.getLogger(__name__)


def _signature_header(request: web.Request) -> str | None:
    for name, value in request.headers.items():
        if "signature" in name.lower():
            return value
    return None


def async_register_webhook(hass: HomeAssistant, entry) -> None:
    entry_id = entry.entry_id
    secret = (entry.options.get(CONF_WEBHOOK_SECRET) or "").strip()

    async def _handle(hass: HomeAssistant, webhook_id: str, request: web.Request) -> web.Response:
        raw = await request.read()

        # If the user pasted SMS.to's webhook signing secret in the options, every
        # callback must carry a valid 't=…,s=…' signature. Otherwise the long random
        # webhook id is the only secret.
        if secret:
            sig = _signature_header(request)
            if not sig or not verify_signature(raw, sig, secret):
                _LOGGER.warning("Rejected SMS.to callback with missing/invalid signature")
                return web.Response(status=401)

        try:
            payload = json.loads(raw) if raw else {}
        except ValueError:
            payload = dict(parse_qsl(raw.decode(errors="replace")))
        if not isinstance(payload, dict):
            payload = {"data": payload}
        if not payload and request.query:
            payload = dict(request.query)

        report = {
            "config_entry_id": entry_id,
            "message_id": payload.get("messageId") or payload.get("message_id") or payload.get("_id"),
            "tracking_id": payload.get("trackingId") or payload.get("tracking_id"),
            "phone": payload.get("phone") or payload.get("to"),
            "status": payload.get("status"),
            "cost": payload.get("cost") or payload.get("price"),
            "parts": payload.get("parts"),
            "received_at": dt_util.utcnow().isoformat(),
            "raw": payload,
        }
        _LOGGER.debug("Delivery report: %s", report)
        hass.bus.async_fire(EVENT_DELIVERY, report)
        async_dispatcher_send(hass, SIGNAL_DELIVERY.format(entry_id), report)
        return web.Response(status=200, text="OK")

    webhook.async_register(
        hass,
        DOMAIN,
        f"SMS.to delivery reports ({entry.title})",
        entry.data[CONF_WEBHOOK_ID],
        _handle,
        allowed_methods=["POST", "GET"],
    )
