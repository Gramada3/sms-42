"""Async client for the SMS.to REST API (all public endpoints)."""
from __future__ import annotations

import hashlib
import hmac
import logging
from typing import Any
from urllib.parse import urlencode

import aiohttp

from .const import REQUEST_TIMEOUT

_LOGGER = logging.getLogger(__name__)

API = "https://api.sms.to"
AUTH = "https://auth.sms.to"
WEB = "https://sms.to/v1"
WEB_API = "https://sms.to/api/v1"

CHANNEL_SMS = "sms"
CHANNEL_FLASH = "fsms"
CHANNEL_VIBER = "viber"


class SmstoError(Exception):
    """Generic SMS.to error."""


class SmstoAuthError(SmstoError):
    """Invalid or revoked API key."""


def _clean(payload: dict[str, Any]) -> dict[str, Any]:
    """Drop None / empty values, like the official SDK does."""
    return {k: v for k, v in payload.items() if v is not None and v != "" and v != []}


def verify_signature(payload: bytes, header: str, secret: str) -> bool:
    """Verify an SMS.to webhook signature header of the form 't=…,s=…'."""
    parts = dict(p.split("=", 1) for p in header.split(",") if "=" in p)
    ts, sig = parts.get("t", "").strip(), parts.get("s", "").strip()
    if not ts.isdigit() or not sig:
        return False
    expected = hmac.new(
        secret.encode(), payload + b"." + ts.encode(), hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, sig)


class SmstoClient:
    """Talks to SMS.to with a bearer API key."""

    def __init__(self, session: aiohttp.ClientSession, api_key: str) -> None:
        self._session = session
        self._api_key = api_key

    # ------------------------------------------------------------------ core
    async def _request(
        self,
        method: str,
        url: str,
        payload: dict[str, Any] | None = None,
        query: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if query:
            # Same encoding as PHP's http_build_query (used by the official SDK):
            # lists become key[0]=a&key[1]=b
            flat: list[tuple[str, Any]] = []
            for k, v in _clean(query).items():
                if isinstance(v, (list, tuple)):
                    flat.extend((f"{k}[{i}]", x) for i, x in enumerate(v))
                else:
                    flat.append((k, v))
            url = f"{url}?{urlencode(flat)}"
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Accept": "application/json",
        }
        try:
            async with self._session.request(
                method,
                url,
                json=_clean(payload) if payload is not None else None,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT),
            ) as resp:
                if resp.status in (401, 403):
                    raise SmstoAuthError(f"HTTP {resp.status}")
                try:
                    body = await resp.json(content_type=None)
                except ValueError:
                    body = {"raw": await resp.text()}
                if resp.status >= 400:
                    msg = body.get("message") if isinstance(body, dict) else None
                    errs = body.get("errors") if isinstance(body, dict) else None
                    raise SmstoError(f"HTTP {resp.status}: {msg or body}{f' {errs}' if errs else ''}")
                if isinstance(body, dict) and body.get("success") is False:
                    raise SmstoError(body.get("message") or "Request refused by SMS.to")
                if isinstance(body, dict):
                    return body
                return {"data": body}
        except aiohttp.ClientError as err:
            raise SmstoError(f"Connection error: {err}") from err
        except TimeoutError as err:
            raise SmstoError("Timeout talking to SMS.to") from err

    # --------------------------------------------------------------- account
    async def get_balance(self) -> tuple[float | None, str | None]:
        data = await self._request("GET", f"{AUTH}/api/balance")
        balance = data.get("balance")
        try:
            balance = round(float(balance), 4) if balance is not None else None
        except (TypeError, ValueError):
            balance = None
        return balance, data.get("currency")

    # -------------------------------------------------------------- sending
    @staticmethod
    def _common(
        sender_id: str | None,
        callback_url: str | None,
        scheduled_for: str | None,
        timezone: str | None,
        bypass_optout: bool | None,
    ) -> dict[str, Any]:
        return {
            "sender_id": sender_id,
            "callback_url": callback_url,
            "scheduled_for": scheduled_for,
            "timezone": timezone,
            "bypass_optout": bypass_optout,
        }

    async def send(
        self,
        message: str,
        targets: list[str],
        sender_id: str | None = None,
        *,
        channel: str = CHANNEL_SMS,
        callback_url: str | None = None,
        scheduled_for: str | None = None,
        timezone: str | None = None,
        bypass_optout: bool | None = None,
        estimate: bool = False,
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Single number → 'to' as string, several → campaign with a list."""
        to: str | list[str] = targets[0] if len(targets) == 1 else targets
        payload = {
            "message": message,
            "to": to,
            **self._common(sender_id, callback_url, scheduled_for, timezone, bypass_optout),
            **(extra or {}),
        }
        action = "estimate" if estimate else "send"
        return await self._request("POST", f"{API}/{channel}/{action}", payload)

    async def send_to_list(
        self,
        message: str,
        list_id: int | str,
        sender_id: str | None = None,
        *,
        channel: str = CHANNEL_SMS,
        callback_url: str | None = None,
        scheduled_for: str | None = None,
        timezone: str | None = None,
        bypass_optout: bool | None = None,
        estimate: bool = False,
    ) -> dict[str, Any]:
        payload = {
            "message": message,
            "list_id": list_id,
            **self._common(sender_id, callback_url, scheduled_for, timezone, bypass_optout),
        }
        action = "estimate" if estimate else "send"
        return await self._request("POST", f"{API}/{channel}/{action}", payload)

    async def send_personalized(
        self,
        messages: list[dict[str, str]],
        sender_id: str | None = None,
        *,
        channel: str = CHANNEL_SMS,
        callback_url: str | None = None,
        scheduled_for: str | None = None,
        timezone: str | None = None,
        bypass_optout: bool | None = None,
        estimate: bool = False,
    ) -> dict[str, Any]:
        payload = {
            "messages": messages,
            **self._common(sender_id, callback_url, scheduled_for, timezone, bypass_optout),
        }
        action = "estimate" if estimate else "send"
        return await self._request("POST", f"{API}/{channel}/{action}", payload)

    # ---------------------------------------------------- messages/campaigns
    async def get_total_messages(self) -> int | None:
        for url in (f"{API}/v2/messages", f"{API}/messages"):
            try:
                data = await self._request("GET", url)
            except SmstoAuthError:
                raise
            except SmstoError:
                continue
            total = data.get("total")
            if total is None and isinstance(data.get("meta"), dict):
                total = data["meta"].get("total")
            if total is not None:
                return int(total)
        return None

    async def list_messages(self, **filters: Any) -> dict[str, Any]:
        return await self._request("GET", f"{API}/v2/messages", query=filters)

    async def get_last_message(self) -> dict[str, Any]:
        return await self._request("GET", f"{API}/last/message")

    async def get_message(self, message_id: str) -> dict[str, Any]:
        return await self._request("GET", f"{API}/message/{message_id}")

    async def list_campaigns(self, **filters: Any) -> dict[str, Any]:
        return await self._request("GET", f"{API}/campaigns", query=filters)

    async def get_last_campaign(self) -> dict[str, Any]:
        return await self._request("GET", f"{API}/last/campaign")

    async def get_campaign(self, campaign_id: str) -> dict[str, Any]:
        return await self._request("GET", f"{API}/campaigns/{campaign_id}")

    async def phone_status(self, phone: str, default_prefix: str | None = None) -> dict[str, Any]:
        return await self._request(
            "POST", f"{API}/phone/status", {"phone": phone, "default_prefix": default_prefix}
        )

    # ---------------------------------------------------- contacts & lists
    async def list_lists(self, name: str | None = None, page: int | None = None) -> dict[str, Any]:
        return await self._request(
            "GET", f"{WEB}/people/lists", query={"name": name, "page": page, "direction": "ASC"}
        )

    async def create_list(self, name: str, description: str = "", share_with_team: bool = False) -> dict[str, Any]:
        return await self._request(
            "POST",
            f"{WEB}/people/lists/create",
            {"name": name, "description": description, "share_with_team": int(share_with_team)},
        )

    async def delete_list(self, list_id: int | str) -> dict[str, Any]:
        return await self._request("DELETE", f"{WEB}/people/lists/{list_id}/delete")

    async def list_contacts(
        self, list_ids: list[int | str] | int | str, limit: int = 100, page: int = 1
    ) -> dict[str, Any]:
        return await self._request(
            "GET",
            f"{WEB}/people/contacts",
            query={
                "list_ids": list_ids,
                "limit": limit,
                "page": page,
                "order_by": "firstname",
                "direction": "ASC",
            },
        )

    async def create_contact(
        self, phone: str, list_ids: list[int | str], **other: Any
    ) -> dict[str, Any]:
        return await self._request(
            "POST", f"{WEB}/people/contacts/create", {"phone": phone, "list_ids": list_ids, **other}
        )

    async def delete_contact(self, phone: str, list_ids: list[int | str] | None = None) -> dict[str, Any]:
        return await self._request(
            "POST", f"{WEB}/people/contacts/delete-phone", {"phone": phone, "list_id": list_ids}
        )

    async def opt_in(self, phone: str, list_ids: list[int | str] | None = None) -> dict[str, Any]:
        return await self._request(
            "POST", f"{WEB}/people/contacts/optin", {"phone": phone, "list_id": list_ids}
        )

    async def opt_out(self, phone: str, list_ids: list[int | str] | None = None) -> dict[str, Any]:
        return await self._request(
            "POST", f"{WEB}/people/contacts/optout", {"phone": phone, "list_id": list_ids}
        )

    async def recent_optouts(self) -> dict[str, Any]:
        return await self._request("GET", f"{WEB}/recent/optouts")

    # ---------------------------------------------------------- lookup (HLR)
    async def lookup(self, phone: str, estimate: bool = False) -> dict[str, Any]:
        url = f"{WEB}/verify/number/estimate" if estimate else f"{WEB}/verify/number"
        return await self._request("POST", url, {"to": phone})

    # ------------------------------------------------------------ shortlinks
    async def create_shortlink(self, name: str, url: str) -> dict[str, Any]:
        return await self._request("POST", f"{WEB_API}/shortlink", {"name": name, "url": url})

    async def list_shortlinks(self, limit: int = 20, page: int = 1) -> dict[str, Any]:
        return await self._request(
            "GET", f"{WEB_API}/shortlinks", query={"limit": limit, "page": page, "sort": "created_at"}
        )

    async def get_shortlink(self, shortlink_id: str) -> dict[str, Any]:
        return await self._request("GET", f"{WEB_API}/shortlinks/{shortlink_id}")

    async def delete_shortlink(self, shortlink_id: str) -> dict[str, Any]:
        return await self._request("POST", f"{WEB_API}/shortlinks/{shortlink_id}/delete")
