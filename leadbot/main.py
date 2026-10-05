import json
import logging

from fastapi import BackgroundTasks, FastAPI, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse

from . import admin, webhook
from .config import Settings
from .content import Content
from .db import Database
from .flow import Bot
from .instagram import InstagramClient, Messenger

log = logging.getLogger(__name__)


def create_app(settings: Settings | None = None, messenger: Messenger | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    db = Database(settings.database_path)
    content = Content.load(settings.content_path)
    bot = Bot(db, content, messenger or InstagramClient(settings), settings.ig_user_id)

    app = FastAPI(title="T1D Lead Bot", docs_url=None, redoc_url=None)
    app.state.settings = settings
    app.state.db = db
    app.state.bot = bot

    @app.get("/health")
    def health():
        return {"ok": True}

    @app.get("/webhook", response_class=PlainTextResponse)
    def verify(mode: str = Query(alias="hub.mode", default=""),
               token: str = Query(alias="hub.verify_token", default=""),
               challenge: str = Query(alias="hub.challenge", default="")):
        """Meta calls this once when you register the webhook URL."""
        if mode == "subscribe" and settings.verify_token and token == settings.verify_token:
            return challenge
        raise HTTPException(status_code=403, detail="Verification failed")

    @app.post("/webhook")
    async def receive(request: Request, background: BackgroundTasks):
        body = await request.body()
        if not webhook.signature_is_valid(settings.app_secret, body,
                                          request.headers.get("X-Hub-Signature-256")):
            raise HTTPException(status_code=403, detail="Bad signature")
        try:
            payload = json.loads(body)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid JSON")
        # Reply to Meta straight away and do the work afterwards.
        background.add_task(process, bot, db, webhook.parse(payload))
        return {"received": True}

    app.include_router(admin.router)
    return app


def process(bot: Bot, db: Database, events: list) -> None:
    for event in events:
        try:
            if isinstance(event, webhook.CommentEvent):
                if db.mark_processed(f"comment:{event.comment_id}"):
                    bot.handle_comment(event.comment_id, event.from_id, event.username,
                                       event.text, event.media_id)
            elif db.mark_processed(f"message:{event.message_id}"):
                bot.handle_message(event.sender_id, event.text, event.payload)
        except Exception:
            log.exception("Failed to handle %r", event)
