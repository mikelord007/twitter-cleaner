from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator


CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS items (
    id          TEXT NOT NULL,
    type        TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'pending',
    url         TEXT,
    tweet_date  TEXT,
    tweet_text  TEXT,
    error_msg   TEXT,
    retry_count INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at  TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (id, type)
);
"""


@dataclass
class ItemStats:
    pending: int = 0
    done: int = 0
    failed: int = 0
    skipped: int = 0

    @property
    def total(self) -> int:
        return self.pending + self.done + self.failed + self.skipped


class ProgressDB:
    def __init__(self, db_path: Path) -> None:
        self._path = db_path
        self._conn = sqlite3.connect(str(db_path))
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute(CREATE_TABLE)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def bulk_insert_pending(
        self, rows: list[tuple[str, str, str, str | None, str | None]]
    ) -> int:
        """Insert (id, type, url, tweet_date, tweet_text) tuples as pending. Ignores existing rows."""
        self._conn.executemany(
            "INSERT OR IGNORE INTO items (id, type, url, tweet_date, tweet_text) VALUES (?, ?, ?, ?, ?)",
            rows,
        )
        self._conn.commit()
        return self._conn.execute("SELECT changes()").fetchone()[0]

    def get_pending(
        self,
        item_types: list[str] | None = None,
        limit: int = 100,
    ) -> list[sqlite3.Row]:
        if item_types:
            placeholders = ",".join("?" * len(item_types))
            return self._conn.execute(
                f"SELECT * FROM items WHERE status IN ('pending', 'failed') "
                f"AND type IN ({placeholders}) AND retry_count < 3 "
                f"ORDER BY created_at LIMIT ?",
                (*item_types, limit),
            ).fetchall()
        return self._conn.execute(
            "SELECT * FROM items WHERE status IN ('pending', 'failed') "
            "AND retry_count < 3 ORDER BY type, created_at LIMIT ?",
            (limit,),
        ).fetchall()

    def mark_done(self, id: str, item_type: str) -> None:
        self._conn.execute(
            "UPDATE items SET status='done', updated_at=datetime('now') WHERE id=? AND type=?",
            (id, item_type),
        )
        self._conn.commit()

    def mark_failed(self, id: str, item_type: str, error: str) -> None:
        self._conn.execute(
            "UPDATE items SET status='failed', error_msg=?, retry_count=retry_count+1, "
            "updated_at=datetime('now') WHERE id=? AND type=?",
            (error, id, item_type),
        )
        self._conn.commit()

    def mark_skipped(self, id: str, item_type: str) -> None:
        self._conn.execute(
            "UPDATE items SET status='skipped', updated_at=datetime('now') WHERE id=? AND type=?",
            (id, item_type),
        )
        self._conn.commit()

    def stats(self, item_types: list[str] | None = None) -> ItemStats:
        if item_types:
            placeholders = ",".join("?" * len(item_types))
            rows = self._conn.execute(
                f"SELECT status, COUNT(*) as n FROM items WHERE type IN ({placeholders}) GROUP BY status",
                tuple(item_types),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT status, COUNT(*) as n FROM items GROUP BY status"
            ).fetchall()
        counts = {r["status"]: r["n"] for r in rows}
        return ItemStats(
            pending=counts.get("pending", 0),
            done=counts.get("done", 0),
            failed=counts.get("failed", 0),
            skipped=counts.get("skipped", 0),
        )

    def stats_by_type(self) -> dict[str, ItemStats]:
        rows = self._conn.execute(
            "SELECT type, status, COUNT(*) as n FROM items GROUP BY type, status"
        ).fetchall()
        result: dict[str, ItemStats] = {}
        for row in rows:
            t = row["type"]
            if t not in result:
                result[t] = ItemStats()
            s = row["status"]
            if s == "pending":
                result[t].pending += row["n"]
            elif s == "done":
                result[t].done += row["n"]
            elif s == "failed":
                result[t].failed += row["n"]
            elif s == "skipped":
                result[t].skipped += row["n"]
        return result

    def reset_status(self, item_type: str | None, from_status: str) -> int:
        if item_type:
            self._conn.execute(
                "UPDATE items SET status='pending', retry_count=0, updated_at=datetime('now') "
                "WHERE type=? AND status=?",
                (item_type, from_status),
            )
        else:
            self._conn.execute(
                "UPDATE items SET status='pending', retry_count=0, updated_at=datetime('now') "
                "WHERE status=?",
                (from_status,),
            )
        self._conn.commit()
        return self._conn.execute("SELECT changes()").fetchone()[0]
