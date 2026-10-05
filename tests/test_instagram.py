import json

import httpx

from leadbot.config import Settings
from leadbot.instagram import InstagramClient, QuickReply


def make(handler, dry_run=False):
    settings = Settings(
        ig_access_token="tok", ig_user_id="123", app_secret="s", verify_token="v",
        graph_host="https://graph.instagram.com", graph_api_version="v23.0",
        admin_username="a", admin_password="p", database_path=":memory:",
        content_path="content.yaml", dry_run=dry_run,
    )
    http = httpx.Client(transport=httpx.MockTransport(handler),
                        headers={"Authorization": "Bearer tok"})
    return InstagramClient(settings, http)


def test_private_reply_request_shape():
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json={"message_id": "x"})

    make(handler).private_reply("c1", "hi", [QuickReply("Yes", "Y")])
    req = seen[0]
    assert str(req.url) == "https://graph.instagram.com/v23.0/123/messages"
    assert req.headers["Authorization"] == "Bearer tok"
    assert json.loads(req.content) == {
        "recipient": {"comment_id": "c1"},
        "message": {"text": "hi", "quick_replies": [
            {"content_type": "text", "title": "Yes", "payload": "Y"}]},
    }


def test_dry_run_sends_nothing():
    def handler(request):
        raise AssertionError("should not be called")

    client = make(handler, dry_run=True)
    client.send_text("u1", "hi")
    client.reply_to_comment("c1", "hi")
