# T1D Lead Bot

An Instagram comment-to-DM funnel for a type 1 diabetes fitness coaching business.

1. You post T1D training content and tell people to **comment a keyword** (e.g. `PLAN`).
2. The bot sends each commenter a **private DM** with your free guide. It also posts a short public "Sent you a DM 📩" reply under the comment.
3. In the DM it asks whether they're happy to answer **3 quick qualifying questions**. Only people who tap **Yes** are asked, and only their answers are stored.
4. It asks the questions (goal, training experience, how long they've had T1D), then sends your **booking link**.
5. Each lead shows up in a **password-protected dashboard**. There you track status (new → qualified → contacted → booked → client), add notes, set follow-up dates and export to CSV.

People can also DM a keyword directly instead of commenting.

## How it stays within Instagram's rules and privacy law

- **It never messages anyone first.** It only replies to someone who just commented a keyword or DMed you. Meta's Messaging API allows this: one private reply per comment, and replies within 24 hours of the person's last message.
- **Ordinary DMs are left alone.** Messages without a keyword go to your normal Instagram inbox, and the bot doesn't respond.
- **It asks for consent before collecting health data.** Answers about diabetes are "special category" data under UK/EU GDPR. Nothing is stored until the person explicitly says yes. Messages they send before that aren't logged.
- **People can opt out.** `STOP` ends automated messages. `DELETE` wipes everything stored about them. Both are permanent: the bot keeps only their ID so it never auto-messages them again.
- **You take over after the questions.** Once the questions are done, the bot stops replying and flags the lead as "Needs your reply" in the dashboard.

You still need a privacy policy that covers what you collect. Link it in `content.yaml` (`links.privacy`). Meta also requires one for app review.

## Customising what the bot says

Everything the bot says is in [`content.yaml`](content.yaml): keywords, links, every message and the questions. Edit it and restart the app. Use `{name}` for the person's username, and `{guide}`, `{booking}` or `{privacy}` for your links.

## Setup

### 1. Run it

You need Python 3.11+.

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # then fill it in (see below)
uvicorn leadbot.main:create_app --factory --host 0.0.0.0 --port 8000
```

- Dashboard: `http://localhost:8000/admin`. It uses the `ADMIN_USERNAME` and `ADMIN_PASSWORD` login from `.env`.
- Set `DRY_RUN=1` to log messages instead of sending them while you test.

Instagram has to be able to reach the app, so for real use deploy it to a host with HTTPS, e.g. Render, Railway or Fly.io. Use the start command above with `--port $PORT`. Leads are stored in SQLite (`DATABASE_PATH`), so give the app a **persistent disk** and point `DATABASE_PATH` at it. Otherwise leads are lost on each redeploy.

### 2. Connect Instagram

1. Make your Instagram account a **Professional account** (Business or Creator). A Facebook Page isn't needed.
2. In the Instagram app, go to **Settings → Messages and story replies → Message controls → Connected tools** and turn on **Allow access to messages**.
3. At [developers.facebook.com](https://developers.facebook.com), create an app and pick the **Instagram** use case. Then choose **"API setup with Instagram login"**.
4. Add your Instagram account and **generate an access token**. Put it in `IG_ACCESS_TOKEN`, and put the account's numeric ID shown there in `IG_USER_ID`. Copy the **App secret** (App settings → Basic) into `APP_SECRET`.
5. Under **Configure webhooks**:
   - Callback URL: `https://YOUR-DOMAIN/webhook`
   - Verify token: any random string. Set the same value as `VERIFY_TOKEN` in `.env`.
   - Subscribe to the **`comments`** and **`messages`** fields.
6. To test before app review, use a second Instagram account added as a tester in the app's **Roles**. Comment a keyword from that account on one of your posts.
7. **Go live:** submit the app for **App Review** to get Advanced Access for `instagram_business_basic`, `instagram_business_manage_messages` and `instagram_business_manage_comments`. Until then, only accounts with a role on the app trigger webhooks. Meta may also ask you to complete Business Verification.

Long-lived Instagram tokens expire after 60 days. Refresh yours in the Meta dashboard before then (or via the `refresh_access_token` endpoint).

## Development

```bash
pip install -r requirements-dev.txt
pytest
```

| File | What it does |
| --- | --- |
| `leadbot/main.py` | App, webhook endpoints, signature check |
| `leadbot/webhook.py` | Parses Instagram webhook payloads |
| `leadbot/flow.py` | The conversation (consent → questions → booking) |
| `leadbot/instagram.py` | Instagram API client |
| `leadbot/db.py` | SQLite storage |
| `leadbot/admin.py` | Dashboard |
| `content.yaml` | Everything the bot says |
