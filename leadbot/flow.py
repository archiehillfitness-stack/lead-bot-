"""The conversation: keyword -> guide + consent -> qualifying questions -> booking link.

Stages a lead moves through:
    consent   waiting for YES/NO to the questions
    q<N>      waiting for the answer to question N (0-based)
    done      finished the questions, handed over to you
    declined  said no to the questions, got the guide only
    stopped   replied STOP

The bot only ever replies to someone who has just messaged or commented.
It never starts a conversation on its own. Answers (which can include
health information) are only stored after the person says YES.
"""
import logging

from .content import Content, normalize
from .db import Database, now
from .instagram import InstagramError, Messenger, QuickReply

log = logging.getLogger(__name__)

CONSENT_YES = "CONSENT_YES"
CONSENT_NO = "CONSENT_NO"
YES_WORDS = {"yes", "y", "yeah", "yep", "sure", "ok", "okay", "go", "yes ask away"}
NO_WORDS = {"no", "n", "nope", "nah", "no thanks", "not now"}
STOP_WORDS = {"stop", "unsubscribe"}
DELETE_WORDS = {"delete", "delete my data"}


class Bot:
    def __init__(self, db: Database, content: Content, messenger: Messenger, own_ig_id: str):
        self.db = db
        self.content = content
        self.ig = messenger
        self.own_ig_id = own_ig_id

    # --- entry points -----------------------------------------------------

    def handle_comment(self, comment_id: str, from_id: str, username: str | None,
                       text: str, media_id: str | None) -> None:
        if from_id == self.own_ig_id or not self.content.matches_keyword(text):
            return
        if self.db.is_opted_out(from_id) or self.db.get_lead(from_id):
            # Already in the funnel (or opted out): don't send the welcome again.
            return

        lead = self.db.create_lead(from_id, username, "comment", media_id, "consent")
        welcome = self.content.message("welcome", username)
        try:
            self.ig.private_reply(comment_id, welcome, self._consent_buttons())
        except InstagramError:
            log.exception("Private reply to comment %s failed", comment_id)
            self.db.update_lead(from_id, needs_reply=1, notes="Automatic DM failed to send.")
            return
        self.db.log_message(lead["ig_id"], "out", welcome)

        if self.content.public_comment_reply:
            try:
                self.ig.reply_to_comment(comment_id, self.content.public_comment_reply)
            except InstagramError:
                log.exception("Public reply to comment %s failed", comment_id)

    def handle_message(self, sender_id: str, text: str | None, payload: str | None) -> None:
        if sender_id == self.own_ig_id:
            return
        text = (text or "").strip()
        command = normalize(text)
        lead = self.db.get_lead(sender_id)

        if lead is None:
            if (self.content.matches_keyword(text) and not self.db.is_opted_out(sender_id)):
                self._start_from_dm(sender_id)
            # Anything else is a normal DM: leave it for you in the Instagram inbox.
            return

        self.db.update_lead(sender_id, last_inbound_at=now())

        if command in DELETE_WORDS:
            self.db.delete_lead(sender_id)
            self.db.opt_out(sender_id)
            self._send(sender_id, self.content.message("deleted"), log_it=False)
            return
        if command in STOP_WORDS and lead["stage"] != "stopped":
            self.db.opt_out(sender_id)
            self.db.update_lead(sender_id, stage="stopped")
            self._send(sender_id, self.content.message("stopped"))
            return

        stage = lead["stage"]
        if lead["consent_at"]:
            self.db.log_message(sender_id, "in", text or f"[{payload}]")

        if stage == "consent":
            self._handle_consent(lead, command, payload)
        elif stage.startswith("q"):
            self._handle_answer(lead, int(stage[1:]), text)
        else:
            # done / declined / stopped: a human takes it from here.
            self.db.update_lead(sender_id, needs_reply=1)

    # --- steps ------------------------------------------------------------

    def _start_from_dm(self, sender_id: str) -> None:
        username = self.ig.get_username(sender_id)
        self.db.create_lead(sender_id, username, "dm", None, "consent")
        self.db.update_lead(sender_id, last_inbound_at=now())
        self._send(sender_id, self.content.message("welcome", username), self._consent_buttons())

    def _handle_consent(self, lead: dict, command: str, payload: str | None) -> None:
        ig_id = lead["ig_id"]
        if payload == CONSENT_YES or command in YES_WORDS:
            self.db.update_lead(ig_id, consent_at=now(), stage="q0")
            self._ask(ig_id, 0)
        elif payload == CONSENT_NO or command in NO_WORDS:
            self.db.update_lead(ig_id, stage="declined", status="not_a_fit")
            self._send(ig_id, self.content.message("declined", lead["username"]))
        else:
            self._send(ig_id, self.content.message("consent_prompt_retry"), self._consent_buttons())

    def _handle_answer(self, lead: dict, index: int, text: str) -> None:
        ig_id = lead["ig_id"]
        questions = self.content.questions
        if index >= len(questions):
            # The question list shrank since this lead started; just finish.
            return self._finish(lead)
        if not text:
            return self._ask(ig_id, index)

        answers = {**lead["answers"], questions[index].key: text}
        self.db.update_lead(ig_id, answers=answers)
        if index + 1 < len(questions):
            self.db.update_lead(ig_id, stage=f"q{index + 1}")
            self._ask(ig_id, index + 1)
        else:
            self._finish(lead)

    def _finish(self, lead: dict) -> None:
        self.db.update_lead(lead["ig_id"], stage="done", status="qualified", needs_reply=1)
        self._send(lead["ig_id"], self.content.message("finished", lead["username"]))

    def _ask(self, ig_id: str, index: int) -> None:
        q = self.content.questions[index]
        buttons = [QuickReply(opt, f"ANSWER:{q.key}:{i}") for i, opt in enumerate(q.options)]
        self._send(ig_id, q.text, buttons or None)

    # --- helpers ----------------------------------------------------------

    def _consent_buttons(self) -> list[QuickReply]:
        return [
            QuickReply(self.content.message("consent_yes_button"), CONSENT_YES),
            QuickReply(self.content.message("consent_no_button"), CONSENT_NO),
        ]

    def _send(self, ig_id: str, text: str, buttons: list[QuickReply] | None = None,
              log_it: bool = True) -> None:
        try:
            self.ig.send_text(ig_id, text, buttons)
        except InstagramError:
            log.exception("Sending DM to %s failed", ig_id)
            if self.db.get_lead(ig_id):
                self.db.update_lead(ig_id, needs_reply=1)
            return
        if log_it:
            self.db.log_message(ig_id, "out", text)
