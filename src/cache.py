"""
cache.py — SQLite persistence for PDGA score data

Schema (single table):
  tournament_cache
    tourn_id    TEXT PRIMARY KEY
    scores_json TEXT   — full scores dict serialised as JSON
    cached_at   REAL   — Unix timestamp of last successful PDGA fetch

Usage:
  from cache import save_scores, load_scores, list_cached

The cache file is created automatically next to this script.
Delete scoreboard_cache.db to start fresh.
"""

import json
import sqlite3
import time
from pathlib import Path

# ─────────────────────────────────────────────────────────────
# Config
# ─────────────────────────────────────────────────────────────

# Path to the SQLite database file (sits next to this script)
DB_PATH = Path(__file__).parent.parent / "scoreboard_cache.db"

# How old a cached entry can be before the scraper ignores it on startup.
# During live polling the scraper always refreshes regardless of age;
# this threshold only applies to the "warm from disk on startup" path.
STALE_THRESHOLD_SECONDS = 300   # 5 minutes


# ─────────────────────────────────────────────────────────────
# Internal helpers
# ─────────────────────────────────────────────────────────────

def _connect() -> sqlite3.Connection:
    """Open a connection with WAL mode for safe concurrent reads/writes."""
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.row_factory = sqlite3.Row
    return conn


def _ensure_schema(conn: sqlite3.Connection):
    """Create the cache table if it doesn't exist yet."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS tournament_cache (
            tourn_id    TEXT PRIMARY KEY,
            scores_json TEXT NOT NULL,
            cached_at   REAL NOT NULL
        )
    """)
    conn.commit()


# ─────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────

def save_scores(tourn_id: str, scores: dict) -> None:
    """
    Persist a scores dict for tourn_id.
    Overwrites any existing entry (upsert).
    Called by the scraper after every successful PDGA fetch.
    """
    payload = json.dumps(scores, ensure_ascii=False)
    now     = time.time()
    with _connect() as conn:
        _ensure_schema(conn)
        conn.execute("""
            INSERT INTO tournament_cache (tourn_id, scores_json, cached_at)
            VALUES (?, ?, ?)
            ON CONFLICT(tourn_id) DO UPDATE SET
                scores_json = excluded.scores_json,
                cached_at   = excluded.cached_at
        """, (str(tourn_id), payload, now))
        conn.commit()


def load_scores(tourn_id: str, max_age: int = STALE_THRESHOLD_SECONDS) -> dict | None:
    """
    Load cached scores for tourn_id if they exist and are fresh enough.

    Returns the scores dict if the cache hit is within max_age seconds,
    or None if the entry is missing or stale.

    Pass max_age=0 to always return whatever is cached regardless of age
    (useful for showing something while a fresh fetch is in flight).
    """
    with _connect() as conn:
        _ensure_schema(conn)
        row = conn.execute(
            "SELECT scores_json, cached_at FROM tournament_cache WHERE tourn_id = ?",
            (str(tourn_id),)
        ).fetchone()

    if row is None:
        return None     # never cached

    age = time.time() - row["cached_at"]

    if max_age > 0 and age > max_age:
        print(f"[cache] TournID={tourn_id} cache is {age:.0f}s old"
              f"(threshold {max_age}s) — treating as stale")
        return None

    scores = json.loads(row["scores_json"])
    print(f"[cache] TournID={tourn_id} loaded from disk (age {age:.0f}s)")
    return scores


def list_cached() -> list[dict]:
    """
    Return a list of all cached tournaments with their age.
    Useful for debugging; not exposed as an API route currently.
    """
    with _connect() as conn:
        _ensure_schema(conn)
        rows = conn.execute(
            "SELECT tourn_id, cached_at FROM tournament_cache ORDER BY cached_at DESC"
        ).fetchall()

    now = time.time()
    return [
        {
            "tourn_id":  row["tourn_id"],
            "cached_at": row["cached_at"],
            "age_s":     round(now - row["cached_at"]),
        }
        for row in rows
    ]


def delete_cache(tourn_id: str) -> bool:
    """Remove a specific tournament from the cache. Returns True if a row was deleted."""
    with _connect() as conn:
        _ensure_schema(conn)
        cursor = conn.execute(
            "DELETE FROM tournament_cache WHERE tourn_id = ?",
            (str(tourn_id),)
        )
        conn.commit()
        return cursor.rowcount > 0
