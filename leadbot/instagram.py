"""Thin client for the Instagram Messaging and Comments APIs.

Uses the "Instagram API with Instagram Login". Messages can only be sent to
people who contacted the account first: as a private reply to their comment
(once per comment, within 7 days) or within 24 hours of their last DM.
"""
import logging
from typing import Protocol

import httpx

from .config import Settings

log = logging.getLogger(__name__)


class QuickReply(dict):
    def __init__(self, title: str, payload: str):
        super().__init__(content_type="text", title=title, payload=payload)


class Messenger(Protocol):
    def send_text(self, recipient_id: str, text: str,
                  quick_replies: list[QuickReply] | None = None) -> None: ...

    def private_reply(self, comment_id: str, text: str,
                      quick_replies: list[QuickReply] | None = None) -> None: ...

    def reply_to_comment(self, comment_id: str, text: str) -> None: ...

    def get_username(self, ig_id: str) -> str | None: ...


class InstagramClient:
    def __init__(self, settings: Settings, http: httpx.Client | None = None):
        self._settings = settings
        self._base = f"{settings.graph_host}/{settings.graph_api_version}"
        self._http = http or httpx.Client(
            timeout=15, headers={"Authorization": f"Bearer {settings.ig_access_token}"})

    def send_text(self, recipient_id, text, quick_replies=None):
        self._send({"id": recipient_id}, text, quick_replies)

    def private_reply(self, comment_id, text, quick_replies=None):
        self._send({"comment_id": comment_id}, text, quick_replies)

    def reply_to_comment(self, comment_id, text):
        if self._settings.dry_run:
            log.info("[dry run] public reply to comment %s: %s", comment_id, text)
            return
        r = self._http.post(f"{self._base}/{comment_id}/replies", data={"message": text})
        _raise_for_status(r)

    def get_username(self, ig_id):
        if self._settings.dry_run:
            return None
        try:
            r = self._http.get(f"{self._base}/{ig_id}", params={"fields": "username"})
            r.raise_for_status()
            return r.json().get("username")
        except httpx.HTTPError as exc:
            log.warning("Could not look up username for %s: %s", ig_id, exc)
            return None

    def _send(self, recipient, text, quick_replies):
        message = {"text": text}
        if quick_replies:
            message["quick_replies"] = quick_replies
        if self._settings.dry_run:
            log.info("[dry run] DM to %s: %s %s", recipient, text,
                     [q["title"] for q in quick_replies or []])
            return
        r = self._http.post(f"{self._base}/{self._settings.ig_user_id}/messages",
                            json={"recipient": recipient, "message": message})
        _raise_for_status(r)


class InstagramError(Exception):
    pass


def _raise_for_status(r: httpx.Response) -> None:
    if r.is_error:
        raise InstagramError(f"Instagram API error {r.status_code}: {r.text}")
