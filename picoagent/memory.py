"""Persistent conversation memory backed by SQLite."""

import json
import logging
import sqlite3
from pathlib import Path

log = logging.getLogger(__name__)

DEFAULT_DB_PATH = "/data/picoagent.db"
MEMORY_WINDOW = 20


class Memory:
    """SQLite-backed conversation store. Survives container restarts."""

    def __init__(self, db_path: str = DEFAULT_DB_PATH):
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(db_path)
        self.conn.execute("PRAGMA journal_mode=WAL")
        self._init_tables()
        log.info("Memory opened: %s", db_path)

    def _init_tables(self):
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                conv_key TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                tool_call_id TEXT,
                tool_calls TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE INDEX IF NOT EXISTS idx_conv ON messages(conv_key);
        """)

    def load(self, conv_key: str) -> list[dict]:
        """Load the last MEMORY_WINDOW messages for a conversation."""
        rows = self.conn.execute(
            "SELECT role, content, tool_call_id, tool_calls FROM messages "
            "WHERE conv_key = ? ORDER BY id DESC LIMIT ?",
            (conv_key, MEMORY_WINDOW),
        ).fetchall()
        messages = []
        for role, content, tool_call_id, tool_calls_json in reversed(rows):
            msg = {"role": role, "content": content}
            if tool_call_id:
                msg["tool_call_id"] = tool_call_id
            if tool_calls_json:
                msg["tool_calls"] = json.loads(tool_calls_json)
            messages.append(msg)
        return messages

    def save(self, conv_key: str, msg: dict):
        """Persist a single message."""
        self.conn.execute(
            "INSERT INTO messages (conv_key, role, content, tool_call_id, tool_calls) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                conv_key,
                msg["role"],
                msg.get("content", ""),
                msg.get("tool_call_id"),
                json.dumps(msg["tool_calls"]) if msg.get("tool_calls") else None,
            ),
        )
        self.conn.commit()

    def trim(self, conv_key: str):
        """Keep only the last MEMORY_WINDOW messages per conversation."""
        self.conn.execute(
            "DELETE FROM messages WHERE conv_key = ? AND id NOT IN "
            "(SELECT id FROM messages WHERE conv_key = ? ORDER BY id DESC LIMIT ?)",
            (conv_key, conv_key, MEMORY_WINDOW),
        )
        self.conn.commit()

    def close(self):
        self.conn.close()
