"""Verifying and unpacking Instagram webhook deliveries."""
import hashlib
import hmac
from dataclasses import dataclass


def signature_is_valid(app_secret: str, body: bytes, header: str | None) -> bool:
    if not app_secret or not header or not header.startswith("sha256="):
        return False
    expected = hmac.new(app_secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header.removeprefix("sha256="))


@dataclass(frozen=True)
class CommentEvent:
    comment_id: str
    from_id: str
    username: str | None
    text: str
    media_id: str | None


@dataclass(frozen=True)
class MessageEvent:
    message_id: str
    sender_id: str
    text: str | None
    payload: str | None


def parse(payload: dict) -> list[CommentEvent | MessageEvent]:
    events: list[CommentEvent | MessageEvent] = []
    if payload.get("object") != "instagram":
        return events
    for entry in payload.get("entry") or []:
        for change in entry.get("changes") or []:
            if change.get("field") != "comments":
                continue
            value = change.get("value") or {}
            sender = value.get("from") or {}
            if not value.get("id") or not sender.get("id"):
                continue
            events.append(CommentEvent(
                comment_id=value["id"],
                from_id=sender["id"],
                username=sender.get("username"),
                text=value.get("text") or "",
                media_id=(value.get("media") or {}).get("id"),
            ))
        for item in entry.get("messaging") or []:
            message = item.get("message")
            sender_id = (item.get("sender") or {}).get("id")
            if not message or not sender_id or message.get("is_echo") or message.get("is_deleted"):
                continue
            events.append(MessageEvent(
                message_id=message.get("mid") or f"{sender_id}:{item.get('timestamp')}",
                sender_id=sender_id,
                text=message.get("text"),
                payload=(message.get("quick_reply") or {}).get("payload"),
            ))
    return events
