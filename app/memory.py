"""Glass-box memory: a single SQLite file the user owns, reads and can delete from.

Every row records where it came from, so the UI can show provenance for anything
the agent claims to know. Nothing is hidden in an opaque vector index.
"""

from __future__ import annotations

import json
import re
import sqlite3
import time
from pathlib import Path
from typing import Any

KINDS = ("fact", "preference", "project", "person", "task", "note")

# Jaccard token overlap above which two memories are treated as the same fact.
DUPLICATE_THRESHOLD = 0.8
# A shorter memory almost entirely inside a longer one is the same fact restated.
CONTAINMENT_THRESHOLD = 0.9
MIN_TOKENS_FOR_CONTAINMENT = 6

_SCHEMA = """
CREATE TABLE IF NOT EXISTS memories (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at  REAL NOT NULL,
    updated_at  REAL NOT NULL,
    kind        TEXT NOT NULL DEFAULT 'note',
    text        TEXT NOT NULL,
    tags        TEXT NOT NULL DEFAULT '[]',
    source      TEXT NOT NULL DEFAULT 'agent',
    pinned      INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_memories_kind ON memories(kind);
CREATE INDEX IF NOT EXISTS idx_memories_updated ON memories(updated_at DESC);
"""

_STOPWORDS = {
    "the", "a", "an", "and", "or", "but", "if", "of", "to", "in", "on", "for",
    "with", "is", "are", "was", "were", "be", "been", "it", "its", "that",
    "this", "i", "me", "my", "you", "your", "do", "does", "did", "what",
    "when", "where", "who", "how", "about", "at", "as", "by", "from",
}


def _tokens(text: str) -> list[str]:
    words = re.findall(r"[a-z0-9]+", text.lower())
    return [w for w in words if len(w) > 2 and w not in _STOPWORDS]


class MemoryStore:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as c:
            c.executescript(_SCHEMA)

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    @staticmethod
    def _row(row: sqlite3.Row) -> dict[str, Any]:
        d = dict(row)
        try:
            d["tags"] = json.loads(d["tags"])
        except (json.JSONDecodeError, TypeError):
            d["tags"] = []
        d["pinned"] = bool(d["pinned"])
        return d

    def add(
        self,
        text: str,
        kind: str = "note",
        tags: list[str] | None = None,
        source: str = "agent",
    ) -> dict[str, Any]:
        text = (text or "").strip()
        if not text:
            raise ValueError("memory text must not be empty")
        if kind not in KINDS:
            kind = "note"

        # Collapse near-duplicates instead of stacking them. The agent can be
        # prompted not to repeat itself, but the store should not depend on that:
        # duplicate rows are what turn an inspectable memory pane into noise.
        incoming = set(_tokens(text))
        if incoming:
            for row in self.recent(limit=500):
                existing = set(_tokens(row["text"]))
                if not existing:
                    continue
                shared = len(incoming & existing)
                jaccard = shared / len(incoming | existing)
                # Containment catches "same fact, restated with more detail",
                # which scores low on Jaccard. Gated on a minimum length so a
                # short distinct memory is never swallowed by a longer one.
                smaller = min(len(incoming), len(existing))
                contained = (
                    smaller >= MIN_TOKENS_FOR_CONTAINMENT
                    and shared / smaller >= CONTAINMENT_THRESHOLD
                )
                if jaccard >= DUPLICATE_THRESHOLD or contained:
                    merged = self.update(
                        row["id"],
                        text=text if len(text) > len(row["text"]) else row["text"],
                        tags=sorted(set(row["tags"]) | set(tags or [])),
                    )
                    merged["deduped"] = True
                    return merged

        now = time.time()
        with self._conn() as c:
            cur = c.execute(
                "INSERT INTO memories (created_at, updated_at, kind, text, tags, source)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (now, now, kind, text, json.dumps(tags or []), source),
            )
            row = c.execute(
                "SELECT * FROM memories WHERE id = ?", (cur.lastrowid,)
            ).fetchone()
        return self._row(row)

    def recent(self, limit: int = 200) -> list[dict[str, Any]]:
        with self._conn() as c:
            rows = c.execute(
                "SELECT * FROM memories ORDER BY pinned DESC, updated_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [self._row(r) for r in rows]

    def get(self, mem_id: int) -> dict[str, Any] | None:
        with self._conn() as c:
            row = c.execute("SELECT * FROM memories WHERE id = ?", (mem_id,)).fetchone()
        return self._row(row) if row else None

    def update(self, mem_id: int, **fields: Any) -> dict[str, Any] | None:
        allowed = {"text", "kind", "tags", "pinned"}
        sets, values = [], []
        for key, value in fields.items():
            if key not in allowed or value is None:
                continue
            if key == "tags":
                value = json.dumps(value)
            elif key == "pinned":
                value = int(bool(value))
            elif key == "kind" and value not in KINDS:
                continue
            sets.append(f"{key} = ?")
            values.append(value)
        if not sets:
            return self.get(mem_id)
        sets.append("updated_at = ?")
        values.extend([time.time(), mem_id])
        with self._conn() as c:
            c.execute(f"UPDATE memories SET {', '.join(sets)} WHERE id = ?", values)
        return self.get(mem_id)

    def delete(self, mem_id: int) -> bool:
        with self._conn() as c:
            cur = c.execute("DELETE FROM memories WHERE id = ?", (mem_id,))
        return cur.rowcount > 0

    def wipe(self) -> int:
        with self._conn() as c:
            cur = c.execute("DELETE FROM memories")
        return cur.rowcount

    def search(self, query: str, limit: int = 8) -> list[dict[str, Any]]:
        """Token-overlap ranking over the whole table.

        Deliberately simple and inspectable: the score is the number of query
        tokens present in the memory, so a user can always see why a row matched.
        """
        terms = set(_tokens(query))
        rows = self.recent(limit=1000)
        if not terms:
            return rows[:limit]
        scored = []
        for row in rows:
            haystack = f"{row['text']} {' '.join(row['tags'])} {row['kind']}".lower()
            hits = [t for t in terms if t in haystack]
            if not hits:
                continue
            score = len(hits) / len(terms) + (0.5 if row["pinned"] else 0.0)
            scored.append((score, row))
        scored.sort(key=lambda pair: pair[0], reverse=True)
        return [row for _, row in scored[:limit]]

    def context_block(self, query: str, limit: int = 8) -> str:
        """Pinned memories plus the best matches, rendered for the system prompt."""
        pinned = [m for m in self.recent(limit=50) if m["pinned"]]
        matched = self.search(query, limit=limit)
        seen: set[int] = set()
        chosen: list[dict[str, Any]] = []
        for mem in pinned + matched:
            if mem["id"] in seen:
                continue
            seen.add(mem["id"])
            chosen.append(mem)
        if not chosen:
            return "(no stored memories yet)"
        return "\n".join(
            f"- [#{m['id']} {m['kind']}] {m['text']}" for m in chosen[: limit + 5]
        )
