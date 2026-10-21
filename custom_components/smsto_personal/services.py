"""All SMS.to actions exposed to Home Assistant."""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from ._compat import vol

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant, ServiceCall, ServiceResponse, SupportsResponse
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv

from . import SmstoConfigEntry, async_send, entry_option, webhook_url
from .api import CHANNEL_FLASH, CHANNEL_SMS, CHANNEL_VIBER, SmstoError
from .const import *  # noqa: F403,F401 — all service/attr names

CHANNELS = {"sms": CHANNEL_SMS, "flash": CHANNEL_FLASH, "viber": CHANNEL_VIBER}

BASE = {vol.Optional(ATTR_CONFIG_ENTRY): cv.string}

SEND_OPTS = {
    vol.Optional(ATTR_SENDER_ID): cv.string,
    vol.Optional(ATTR_SCHEDULED_FOR): cv.string,
    vol.Optional(ATTR_TIMEZONE): cv.string,
    vol.Optional(ATTR_BYPASS_OPTOUT): cv.boolean,
    vol.Optional(ATTR_CALLBACK_URL): cv.url,
}

TARGETS = vol.All(cv.ensure_list_csv, [cv.string])
IDS = vol.All(cv.ensure_list_csv, [cv.string])

SEND_SCHEMA = vol.Schema(
    {
        **BASE,
        **SEND_OPTS,
        vol.Required(ATTR_MESSAGE): cv.string,
        vol.Optional(ATTR_TITLE): cv.string,
        vol.Optional(ATTR_TARGET): TARGETS,
    }
)
VIBER_SCHEMA = SEND_SCHEMA.extend(
    {
        vol.Optional(ATTR_VIBER_IMAGE): cv.url,
        vol.Optional(ATTR_VIBER_TARGET): cv.url,
        vol.Optional(ATTR_VIBER_CAPTION): cv.string,
    }
)
ESTIMATE_SCHEMA = SEND_SCHEMA.extend(
    {
        vol.Optional(ATTR_CHANNEL, default="sms"): vol.In(list(CHANNELS)),
        vol.Optional(ATTR_LIST_ID): cv.string,
    }
)
LIST_SEND_SCHEMA = vol.Schema(
    {
        **BASE,
        **SEND_OPTS,
        vol.Required(ATTR_LIST_ID): cv.string,
        vol.Required(ATTR_MESSAGE): cv.string,
        vol.Optional(ATTR_CHANNEL, default="sms"): vol.In(list(CHANNELS)),
        vol.Optional(ATTR_ESTIMATE_ONLY, default=False): cv.boolean,
    }
)
PERSONALIZED_SCHEMA = vol.Schema(
    {
        **BASE,
        **SEND_OPTS,
        vol.Required(ATTR_MESSAGES): vol.All(
            cv.ensure_list,
            [vol.Schema({vol.Required("to"): cv.string, vol.Required("message"): cv.string})],
        ),
        vol.Optional(ATTR_CHANNEL, default="sms"): vol.In(list(CHANNELS)),
        vol.Optional(ATTR_ESTIMATE_ONLY, default=False): cv.boolean,
    }
)
ID_SCHEMA = vol.Schema({**BASE, vol.Required(ATTR_ID): cv.string})
PAGE_SCHEMA = vol.Schema(
    {
        **BASE,
        vol.Optional(ATTR_LIMIT): vol.All(vol.Coerce(int), vol.Range(1, 1000)),
        vol.Optional(ATTR_PAGE): vol.All(vol.Coerce(int), vol.Range(min=1)),
    },
    extra=vol.ALLOW_EXTRA,
)
PHONE_SCHEMA = vol.Schema(
    {
        **BASE,
        vol.Required(ATTR_PHONE): cv.string,
        vol.Optional(ATTR_LIST_IDS): IDS,
        vol.Optional(ATTR_DEFAULT_PREFIX): cv.string,
        vol.Optional(ATTR_ESTIMATE_ONLY, default=False): cv.boolean,
    }
)
CONTACT_SCHEMA = vol.Schema(
    {
        **BASE,
        vol.Required(ATTR_PHONE): cv.string,
        vol.Required(ATTR_LIST_IDS): IDS,
        vol.Optional(ATTR_FIRSTNAME): cv.string,
        vol.Optional(ATTR_LASTNAME): cv.string,
        vol.Optional(ATTR_EMAIL): cv.string,
    }
)
CREATE_LIST_SCHEMA = vol.Schema(
    {
        **BASE,
        vol.Required(ATTR_NAME): cv.string,
        vol.Optional(ATTR_DESCRIPTION, default=""): cv.string,
        vol.Optional(ATTR_SHARE, default=False): cv.boolean,
    }
)
LISTS_SCHEMA = vol.Schema(
    {
        **BASE,
        vol.Optional(ATTR_NAME): cv.string,
        vol.Optional(ATTR_PAGE): vol.Coerce(int),
    }
)
CONTACTS_SCHEMA = vol.Schema(
    {
        **BASE,
        vol.Required(ATTR_LIST_IDS): IDS,
        vol.Optional(ATTR_LIMIT, default=100): vol.Coerce(int),
        vol.Optional(ATTR_PAGE, default=1): vol.Coerce(int),
    }
)
SHORTLINK_SCHEMA = vol.Schema(
    {**BASE, vol.Required(ATTR_NAME): cv.string, vol.Required(ATTR_URL): cv.url}
)
BASE_SCHEMA = vol.Schema(BASE)


def _entry(hass: HomeAssistant, call: ServiceCall) -> SmstoConfigEntry:
    entry_id = call.data.get(ATTR_CONFIG_ENTRY)
    entries = [
        e
        for e in hass.config_entries.async_entries(DOMAIN)
        if e.state is ConfigEntryState.LOADED and (not entry_id or e.entry_id == entry_id)
    ]
    if not entries:
        raise ServiceValidationError(
            "No loaded SMS.to (personal) account" + (f" with id {entry_id}" if entry_id else "")
        )
    return entries[0]


def _opts(call: ServiceCall) -> dict[str, Any]:
    d = call.data
    return {
        "scheduled_for": d.get(ATTR_SCHEDULED_FOR),
        "timezone": d.get(ATTR_TIMEZONE),
        "bypass_optout": d.get(ATTR_BYPASS_OPTOUT),
        "callback_url": d.get(ATTR_CALLBACK_URL),
    }


def _common_for_client(hass, entry, call) -> dict[str, Any]:
    o = _opts(call)
    o["callback_url"] = o["callback_url"] or webhook_url(hass, entry)
    if o["scheduled_for"] and not o["timezone"]:
        o["timezone"] = entry_option(entry, CONF_TIMEZONE) or None
    return o


def _wrap(result: Any) -> dict[str, Any]:
    return result if isinstance(result, dict) else {"data": result}


def async_register_services(hass: HomeAssistant) -> None:
    if hass.services.has_service(DOMAIN, SERVICE_SEND):
        return

    def reg(name: str, schema: vol.Schema, handler: Callable[[ServiceCall], Awaitable[Any]],
            response: SupportsResponse = SupportsResponse.OPTIONAL) -> None:
        async def _run(call: ServiceCall) -> ServiceResponse:
            try:
                result = await handler(call)
            except SmstoError as err:
                raise HomeAssistantError(f"SMS.to: {err}") from err
            if response is SupportsResponse.NONE:
                return None
            return _wrap(result) if call.return_response else None

        hass.services.async_register(DOMAIN, name, _run, schema=schema, supports_response=response)

    # ---------------------------------------------------------------- send
    def make_send(channel: str, estimate: bool = False):
        async def handler(call: ServiceCall):
            entry = _entry(hass, call)
            d = call.data
            extra = {
                k: d[k]
                for k in (ATTR_VIBER_IMAGE, ATTR_VIBER_TARGET, ATTR_VIBER_CAPTION)
                if k in d
            }
            ch = CHANNELS.get(d.get(ATTR_CHANNEL), channel)
            if estimate and d.get(ATTR_LIST_ID):
                return await entry.runtime_data.client.send_to_list(
                    d[ATTR_MESSAGE], d[ATTR_LIST_ID],
                    d.get(ATTR_SENDER_ID) or entry_option(entry, CONF_SENDER_ID),
                    channel=ch, estimate=True, **_common_for_client(hass, entry, call),
                )
            return await async_send(
                hass, entry, d[ATTR_MESSAGE], d.get(ATTR_TITLE), d.get(ATTR_TARGET),
                d.get(ATTR_SENDER_ID), channel=ch, estimate=estimate,
                extra=extra or None, **_opts(call),
            )
        return handler

    reg(SERVICE_SEND, SEND_SCHEMA, make_send(CHANNEL_SMS))
    reg(SERVICE_SEND_FLASH, SEND_SCHEMA, make_send(CHANNEL_FLASH))
    reg(SERVICE_SEND_VIBER, VIBER_SCHEMA, make_send(CHANNEL_VIBER))
    reg(SERVICE_ESTIMATE, ESTIMATE_SCHEMA, make_send(CHANNEL_SMS, estimate=True),
        SupportsResponse.ONLY)

    async def send_list(call: ServiceCall):
        entry = _entry(hass, call)
        d = call.data
        res = await entry.runtime_data.client.send_to_list(
            d[ATTR_MESSAGE], d[ATTR_LIST_ID],
            d.get(ATTR_SENDER_ID) or entry_option(entry, CONF_SENDER_ID),
            channel=CHANNELS[d[ATTR_CHANNEL]], estimate=d[ATTR_ESTIMATE_ONLY],
            **_common_for_client(hass, entry, call),
        )
        if not d[ATTR_ESTIMATE_ONLY]:
            await entry.runtime_data.coordinator.async_request_refresh()
        return res

    reg(SERVICE_SEND_LIST, LIST_SEND_SCHEMA, send_list)

    async def send_personalized(call: ServiceCall):
        entry = _entry(hass, call)
        d = call.data
        res = await entry.runtime_data.client.send_personalized(
            [dict(m) for m in d[ATTR_MESSAGES]],
            d.get(ATTR_SENDER_ID) or entry_option(entry, CONF_SENDER_ID),
            channel=CHANNELS[d[ATTR_CHANNEL]], estimate=d[ATTR_ESTIMATE_ONLY],
            **_common_for_client(hass, entry, call),
        )
        if not d[ATTR_ESTIMATE_ONLY]:
            await entry.runtime_data.coordinator.async_request_refresh()
        return res

    reg(SERVICE_SEND_PERSONALIZED, PERSONALIZED_SCHEMA, send_personalized)

    # ------------------------------------------------- messages / campaigns
    def client(call):
        return _entry(hass, call).runtime_data.client

    def page_filters(call):
        return {k: v for k, v in call.data.items() if k != ATTR_CONFIG_ENTRY}

    reg(SERVICE_GET_MESSAGE, ID_SCHEMA,
        lambda c: client(c).get_message(c.data[ATTR_ID]), SupportsResponse.ONLY)
    reg(SERVICE_LIST_MESSAGES, PAGE_SCHEMA,
        lambda c: client(c).list_messages(**page_filters(c)), SupportsResponse.ONLY)
    reg(SERVICE_GET_CAMPAIGN, ID_SCHEMA,
        lambda c: client(c).get_campaign(c.data[ATTR_ID]), SupportsResponse.ONLY)
    reg(SERVICE_LIST_CAMPAIGNS, PAGE_SCHEMA,
        lambda c: client(c).list_campaigns(**page_filters(c)), SupportsResponse.ONLY)
    reg(SERVICE_PHONE_STATUS, PHONE_SCHEMA,
        lambda c: client(c).phone_status(c.data[ATTR_PHONE], c.data.get(ATTR_DEFAULT_PREFIX)),
        SupportsResponse.ONLY)
    reg(SERVICE_LOOKUP, PHONE_SCHEMA,
        lambda c: client(c).lookup(c.data[ATTR_PHONE], c.data[ATTR_ESTIMATE_ONLY]),
        SupportsResponse.ONLY)

    # --------------------------------------------------- contacts / lists
    reg(SERVICE_LIST_LISTS, LISTS_SCHEMA,
        lambda c: client(c).list_lists(c.data.get(ATTR_NAME), c.data.get(ATTR_PAGE)),
        SupportsResponse.ONLY)
    reg(SERVICE_CREATE_LIST, CREATE_LIST_SCHEMA,
        lambda c: client(c).create_list(c.data[ATTR_NAME], c.data[ATTR_DESCRIPTION], c.data[ATTR_SHARE]))
    reg(SERVICE_DELETE_LIST, ID_SCHEMA,
        lambda c: client(c).delete_list(c.data[ATTR_ID]))
    reg(SERVICE_LIST_CONTACTS, CONTACTS_SCHEMA,
        lambda c: client(c).list_contacts(c.data[ATTR_LIST_IDS], c.data[ATTR_LIMIT], c.data[ATTR_PAGE]),
        SupportsResponse.ONLY)

    async def create_contact(call: ServiceCall):
        d = call.data
        other = {k: d[k] for k in (ATTR_FIRSTNAME, ATTR_LASTNAME, ATTR_EMAIL) if k in d}
        return await client(call).create_contact(d[ATTR_PHONE], d[ATTR_LIST_IDS], **other)

    reg(SERVICE_CREATE_CONTACT, CONTACT_SCHEMA, create_contact)
    reg(SERVICE_DELETE_CONTACT, PHONE_SCHEMA,
        lambda c: client(c).delete_contact(c.data[ATTR_PHONE], c.data.get(ATTR_LIST_IDS)))
    reg(SERVICE_OPT_IN, PHONE_SCHEMA,
        lambda c: client(c).opt_in(c.data[ATTR_PHONE], c.data.get(ATTR_LIST_IDS)))
    reg(SERVICE_OPT_OUT, PHONE_SCHEMA,
        lambda c: client(c).opt_out(c.data[ATTR_PHONE], c.data.get(ATTR_LIST_IDS)))
    reg(SERVICE_RECENT_OPTOUTS, BASE_SCHEMA,
        lambda c: client(c).recent_optouts(), SupportsResponse.ONLY)

    # ---------------------------------------------------------- shortlinks
    reg(SERVICE_CREATE_SHORTLINK, SHORTLINK_SCHEMA,
        lambda c: client(c).create_shortlink(c.data[ATTR_NAME], c.data[ATTR_URL]))
    reg(SERVICE_LIST_SHORTLINKS, PAGE_SCHEMA,
        lambda c: client(c).list_shortlinks(c.data.get(ATTR_LIMIT, 20), c.data.get(ATTR_PAGE, 1)),
        SupportsResponse.ONLY)
    reg(SERVICE_DELETE_SHORTLINK, ID_SCHEMA,
        lambda c: client(c).delete_shortlink(c.data[ATTR_ID]))

    # -------------------------------------------------------------- refresh
    async def refresh(call: ServiceCall):
        await _entry(hass, call).runtime_data.coordinator.async_request_refresh()

    reg(SERVICE_REFRESH, BASE_SCHEMA, refresh, SupportsResponse.NONE)
