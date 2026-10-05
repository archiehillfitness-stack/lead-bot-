import hashlib
import hmac
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from leadbot.config import Settings
from leadbot.instagram import InstagramError
from leadbot.main import create_app

ROOT = Path(__file__).resolve().parent.parent
OWN_ID = "17840000000000000"
SECRET = "test-secret"


class FakeMessenger:
    def __init__(self):
        self.sent = []          # (kind, target, text, button titles)
        self.fail = False

    def send_text(self, recipient_id, text, quick_replies=None):
        self._record("dm", recipient_id, text, quick_replies)

    def private_reply(self, comment_id, text, quick_replies=None):
        self._record("private_reply", comment_id, text, quick_replies)

    def reply_to_comment(self, comment_id, text):
        self._record("public_reply", comment_id, text, None)

    def get_username(self, ig_id):
        return "dm_person"

    def _record(self, kind, target, text, quick_replies):
        if self.fail:
            raise InstagramError("boom")
        self.sent.append((kind, target, text, [q["title"] for q in quick_replies or []]))


@pytest.fixture
def env(tmp_path):
    settings = Settings(
        ig_access_token="token", ig_user_id=OWN_ID, app_secret=SECRET, verify_token="verify-me",
        graph_host="https://graph.instagram.com", graph_api_version="v23.0",
        admin_username="admin", admin_password="pw", database_path=str(tmp_path / "t.db"),
        content_path=str(ROOT / "content.yaml"), dry_run=False,
    )
    ig = FakeMessenger()
    app = create_app(settings, ig)
    return TestClient(app), ig, app.state.db


def post(client, payload, secret=SECRET):
    body = json.dumps(payload).encode()
    sig = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return client.post("/webhook", content=body,
                       headers={"X-Hub-Signature-256": sig, "Content-Type": "application/json"})


def comment(cid, user_id, text, username="t1d_lifter"):
    return {"object": "instagram", "entry": [{"id": OWN_ID, "time": 1, "changes": [{
        "field": "comments",
        "value": {"id": cid, "text": text, "from": {"id": user_id, "username": username},
                  "media": {"id": "media1"}},
    }]}]}


_mid = 0


def dm(sender, text, payload=None, echo=False):
    global _mid
    _mid += 1
    message = {"mid": f"m{_mid}", "text": text}
    if payload:
        message["quick_reply"] = {"payload": payload}
    if echo:
        message["is_echo"] = True
    return {"object": "instagram", "entry": [{"id": OWN_ID, "time": 1, "messaging": [{
        "sender": {"id": sender}, "recipient": {"id": OWN_ID}, "timestamp": _mid,
        "message": message,
    }]}]}


def test_webhook_verification(env):
    client, _, _ = env
    ok = client.get("/webhook", params={"hub.mode": "subscribe", "hub.verify_token": "verify-me",
                                        "hub.challenge": "abc"})
    assert ok.status_code == 200 and ok.text == "abc"
    bad = client.get("/webhook", params={"hub.mode": "subscribe", "hub.verify_token": "nope",
                                         "hub.challenge": "abc"})
    assert bad.status_code == 403


def test_rejects_bad_signature(env):
    client, ig, db = env
    assert post(client, comment("c1", "u1", "PLAN"), secret="wrong").status_code == 403
    assert ig.sent == [] and db.get_lead("u1") is None


def test_full_funnel_from_comment(env):
    client, ig, db = env
    post(client, comment("c1", "u1", "plan please!"))

    kind, target, text, buttons = ig.sent[0]
    assert (kind, target) == ("private_reply", "c1")
    assert "@" not in text and "t1d_lifter" in text and "example.com/t1d-lifting-guide" in text
    assert buttons == ["Yes, ask away", "No thanks"]
    assert ig.sent[1][:2] == ("public_reply", "c1")
    assert db.get_lead("u1")["stage"] == "consent"

    post(client, dm("u1", "Yes, ask away", "CONSENT_YES"))
    assert db.get_lead("u1")["consent_at"]
    assert ig.sent[-1][2].startswith("1/3")

    post(client, dm("u1", "Build muscle"))
    post(client, dm("u1", "1-3 years"))
    post(client, dm("u1", "about 8 years"))  # typed, not a button

    lead = db.get_lead("u1")
    assert lead["answers"] == {"goal": "Build muscle", "experience": "1-3 years",
                               "diabetes_duration": "about 8 years"}
    assert lead["stage"] == "done" and lead["status"] == "qualified" and lead["needs_reply"]
    assert "calendly.com" in ig.sent[-1][2]

    # Further messages go to you, not the bot.
    count = len(ig.sent)
    post(client, dm("u1", "what does coaching cost?"))
    assert len(ig.sent) == count


def test_non_keyword_comment_and_own_comments_ignored(env):
    client, ig, db = env
    post(client, comment("c1", "u1", "great post"))
    post(client, comment("c2", OWN_ID, "PLAN"))
    assert ig.sent == [] and db.list_leads() == []


def test_duplicate_deliveries_and_repeat_comments(env):
    client, ig, _ = env
    post(client, comment("c1", "u1", "PLAN"))
    post(client, comment("c1", "u1", "PLAN"))   # Meta retry
    post(client, comment("c2", "u1", "GUIDE"))  # same person again
    assert [s[0] for s in ig.sent] == ["private_reply", "public_reply"]


def test_declining_stores_no_answers(env):
    client, ig, db = env
    post(client, comment("c1", "u1", "PLAN"))
    post(client, dm("u1", "nah"))
    lead = db.get_lead("u1")
    assert lead["stage"] == "declined" and lead["answers"] == {} and not lead["consent_at"]
    assert "enjoy the guide" in ig.sent[-1][2]


def test_unclear_consent_reply_reasks_and_is_not_logged(env):
    client, ig, db = env
    post(client, comment("c1", "u1", "PLAN"))
    post(client, dm("u1", "my a1c is 7.2, is that ok?"))
    assert db.get_lead("u1")["stage"] == "consent"
    assert ig.sent[-1][3] == ["Yes, ask away", "No thanks"]
    assert all(m["direction"] == "out" for m in db.messages_for("u1"))


def test_dm_keyword_starts_funnel_and_other_dms_are_left_alone(env):
    client, ig, db = env
    post(client, dm("u2", "hi, love your page"))
    assert ig.sent == [] and db.get_lead("u2") is None

    post(client, dm("u2", "T1D"))
    assert ig.sent[0][:2] == ("dm", "u2")
    assert db.get_lead("u2")["username"] == "dm_person"


def test_echoes_ignored(env):
    client, ig, db = env
    post(client, dm("u3", "PLAN", echo=True))
    assert ig.sent == [] and db.get_lead("u3") is None


def test_stop(env):
    client, ig, db = env
    post(client, comment("c1", "u1", "PLAN"))
    post(client, dm("u1", "STOP"))
    assert db.get_lead("u1")["stage"] == "stopped"
    assert "won't get any more" in ig.sent[-1][2]
    count = len(ig.sent)
    post(client, dm("u1", "yes"))
    post(client, comment("c9", "u1", "PLAN"))
    assert len(ig.sent) == count
    assert db.get_lead("u1")["needs_reply"]


def test_delete_wipes_data_and_blocks_future_automation(env):
    client, ig, db = env
    post(client, comment("c1", "u1", "PLAN"))
    post(client, dm("u1", "yes"))
    post(client, dm("u1", "Lose fat"))
    post(client, dm("u1", "delete"))
    assert db.get_lead("u1") is None and db.messages_for("u1") == []
    assert "deleted" in ig.sent[-1][2]
    count = len(ig.sent)
    post(client, comment("c2", "u1", "PLAN"))
    post(client, dm("u1", "PLAN"))
    assert len(ig.sent) == count


def test_send_failure_flags_lead(env):
    client, ig, db = env
    ig.fail = True
    post(client, comment("c1", "u1", "PLAN"))
    assert db.get_lead("u1")["needs_reply"]


def test_dashboard(env):
    client, _, db = env
    post(client, comment("c1", "u1", "PLAN"))
    post(client, dm("u1", "yes"))
    post(client, dm("u1", "Lose fat"))

    assert client.get("/admin").status_code == 401
    assert client.get("/admin", auth=("admin", "wrong")).status_code == 401
    page = client.get("/admin", auth=("admin", "pw"))
    assert page.status_code == 200 and "@t1d_lifter" in page.text and "Lose fat" in page.text

    detail = client.get("/admin/leads/u1", auth=("admin", "pw"))
    assert detail.status_code == 200 and "Lose fat" in detail.text

    r = client.post("/admin/leads/u1", auth=("admin", "pw"), follow_redirects=False,
                    data={"status": "booked", "notes": "call Tue", "follow_up_on": "2000-01-01"})
    assert r.status_code == 303
    lead = db.get_lead("u1")
    assert (lead["status"], lead["notes"], lead["needs_reply"]) == ("booked", "call Tue", False)
    due = client.get("/admin?view=follow_up", auth=("admin", "pw"))
    assert "@t1d_lifter" in due.text

    cross = client.post("/admin/leads/u1/delete", auth=("admin", "pw"),
                        headers={"Origin": "https://evil.example"})
    assert cross.status_code == 403

    csv = client.get("/admin/export.csv", auth=("admin", "pw"))
    assert "t1d_lifter" in csv.text and "Lose fat" in csv.text

    client.post("/admin/leads/u1/delete", auth=("admin", "pw"))
    assert db.get_lead("u1") is None
