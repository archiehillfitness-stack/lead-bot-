import json
import sqlite3
import threading
from datetime import datetime, timezone
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS leads (
    ig_id            TEXT PRIMARY KEY,
    username         TEXT,
    source           TEXT NOT NULL,          -- 'comment' or 'dm'
    source_media_id  TEXT,
    stage            TEXT NOT NULL,          -- see flow.py
    consent_at       TEXT,
    answers          TEXT NOT NULL DEFAULT '{}',
    status           TEXT NOT NULL DEFAULT 'new',
    needs_reply      INTEGER NOT NULL DEFAULT 0,
    notes            TEXT NOT NULL DEFAULT '',
    follow_up_on     TEXT,
    last_inbound_at  TEXT,
    created_at       TEXT NOT NULL,
    updated_at       TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS messages (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ig_id       TEXT NOT NULL,
    direction   TEXT NOT NULL,               -- 'in' or 'out'
    text        TEXT NOT NULL,
    created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS messages_ig_id ON messages (ig_id);

-- People who replied STOP or DELETE. Only the ID is kept, so the bot never
-- messages them automatically again.
CREATE TABLE IF NOT EXISTS opt_outs (
    ig_id       TEXT PRIMARY KEY,
    created_at  TEXT NOT NULL
);

-- Webhook deliveries can be retried; this stops us acting twice.
CREATE TABLE IF NOT EXISTS processed_events (
    event_id    TEXT PRIMARY KEY,
    created_at  TEXT NOT NULL
);
"""

STATUSES = ["new", "qualified", "contacted", "booked", "client", "not_a_fit"]


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Database:
    def __init__(self, path: str):
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        with self._lock:
            self._conn.executescript(SCHEMA)
            self._conn.commit()

    def _execute(self, sql: str, params: tuple | dict = ()) -> sqlite3.Cursor:
        with self._lock:
            cur = self._conn.execute(sql, params)
            self._conn.commit()
            return cur

    # --- events -----------------------------------------------------------

    def mark_processed(self, event_id: str) -> bool:
        """Record an event. Returns False if it was already processed."""
        cur = self._execute(
            "INSERT OR IGNORE INTO processed_events (event_id, created_at) VALUES (?, ?)",
            (event_id, now()),
        )
        return cur.rowcount == 1

    # --- opt-outs ---------------------------------------------------------

    def is_opted_out(self, ig_id: str) -> bool:
        return self._execute("SELECT 1 FROM opt_outs WHERE ig_id = ?", (ig_id,)).fetchone() is not None

    def opt_out(self, ig_id: str) -> None:
        self._execute(
            "INSERT OR IGNORE INTO opt_outs (ig_id, created_at) VALUES (?, ?)", (ig_id, now())
        )

    # --- leads ------------------------------------------------------------

    def get_lead(self, ig_id: str) -> dict[str, Any] | None:
        row = self._execute("SELECT * FROM leads WHERE ig_id = ?", (ig_id,)).fetchone()
        return _lead(row) if row else None

    def create_lead(self, ig_id: str, username: str | None, source: str,
                    source_media_id: str | None, stage: str) -> dict[str, Any]:
        ts = now()
        self._execute(
            """INSERT INTO leads (ig_id, username, source, source_media_id, stage,
                                  created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (ig_id, username, source, source_media_id, stage, ts, ts),
        )
        return self.get_lead(ig_id)

    def update_lead(self, ig_id: str, **fields: Any) -> None:
        if "answers" in fields:
            fields["answers"] = json.dumps(fields["answers"])
        fields["updated_at"] = now()
        assignments = ", ".join(f"{k} = :{k}" for k in fields)
        self._execute(f"UPDATE leads SET {assignments} WHERE ig_id = :ig_id", {**fields, "ig_id": ig_id})

    def delete_lead(self, ig_id: str) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM messages WHERE ig_id = ?", (ig_id,))
            self._conn.execute("DELETE FROM leads WHERE ig_id = ?", (ig_id,))
            self._conn.commit()

    def list_leads(self, status: str | None = None, needs_reply: bool = False,
                   follow_up_due: bool = False) -> list[dict[str, Any]]:
        clauses, params = [], []
        if status:
            clauses.append("status = ?")
            params.append(status)
        if needs_reply:
            clauses.append("needs_reply = 1")
        if follow_up_due:
            clauses.append("follow_up_on IS NOT NULL AND follow_up_on <= date('now')")
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = self._execute(
            f"SELECT * FROM leads {where} ORDER BY needs_reply DESC, updated_at DESC", tuple(params)
        ).fetchall()
        return [_lead(r) for r in rows]

    def counts(self) -> dict[str, int]:
        rows = self._execute("SELECT status, COUNT(*) AS n FROM leads GROUP BY status").fetchall()
        counts = {s: 0 for s in STATUSES}
        counts.update({r["status"]: r["n"] for r in rows})
        counts["needs_reply"] = self._execute(
            "SELECT COUNT(*) FROM leads WHERE needs_reply = 1").fetchone()[0]
        counts["follow_up_due"] = self._execute(
            "SELECT COUNT(*) FROM leads WHERE follow_up_on IS NOT NULL AND follow_up_on <= date('now')"
        ).fetchone()[0]
        return counts

    # --- messages ---------------------------------------------------------

    def log_message(self, ig_id: str, direction: str, text: str) -> None:
        self._execute(
            "INSERT INTO messages (ig_id, direction, text, created_at) VALUES (?, ?, ?, ?)",
            (ig_id, direction, text, now()),
        )

    def messages_for(self, ig_id: str) -> list[dict[str, Any]]:
        rows = self._execute(
            "SELECT * FROM messages WHERE ig_id = ? ORDER BY id", (ig_id,)).fetchall()
        return [dict(r) for r in rows]


def _lead(row: sqlite3.Row) -> dict[str, Any]:
    lead = dict(row)
    lead["answers"] = json.loads(lead["answers"] or "{}")
    lead["needs_reply"] = bool(lead["needs_reply"])
    return lead
