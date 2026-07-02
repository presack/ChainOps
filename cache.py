"""SQLite-backed result cache for ChainOps.

Adapted from StealthOps' cache.py. The one behavioral difference: confirmed
on-chain data never changes, so callers can pass ttl=None for scopes keyed
to a confirmed txid/block (get() then never treats the row as stale). The
sweep() housekeeping pass still reclaims very old rows regardless of ttl —
that's disk hygiene, not a correctness concern, since re-fetching an
immutable confirmed record returns byte-identical data.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import time

_TTL_DEFAULT = 21600     # 6 h — balances, unconfirmed/mempool data, prices
_SWEEP_AGE = 7776000     # 90 d — sweep threshold


def _db_path() -> str:
    return os.environ.get("CACHE_PATH", os.path.join("cache", "chainops.db"))


def _open() -> sqlite3.Connection:
    path = _db_path()
    dirname = os.path.dirname(os.path.abspath(path))
    os.makedirs(dirname, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS result_cache (
            key        TEXT PRIMARY KEY,
            target     TEXT NOT NULL,
            scope      TEXT NOT NULL,
            payload    TEXT NOT NULL,
            fetched_at INTEGER NOT NULL
        )
    """)
    conn.commit()
    return conn


def _cache_key(target: str, scope: str) -> str:
    return hashlib.sha256(f"{target.lower()}|{scope}".encode()).hexdigest()


def get(target: str, scope: str, ttl: int | None = _TTL_DEFAULT) -> tuple[dict, int] | None:
    """Return (payload, fetched_at) for (target, scope), or None on miss/expiry.

    ttl=None means the entry never expires by age (use for confirmed,
    immutable on-chain data keyed by txid/block height).
    """
    key = _cache_key(target, scope)
    try:
        conn = _open()
        try:
            row = conn.execute(
                "SELECT payload, fetched_at FROM result_cache WHERE key = ?", (key,)
            ).fetchone()
        finally:
            conn.close()
        if row is None:
            return None
        payload_json, fetched_at = row
        if ttl is not None and time.time() - fetched_at > ttl:
            return None
        return json.loads(payload_json), int(fetched_at)
    except Exception:
        return None


def put(target: str, scope: str, payload: dict) -> None:
    """Store payload for (target, scope). Silently swallows errors."""
    key = _cache_key(target, scope)
    try:
        conn = _open()
        try:
            conn.execute(
                "INSERT OR REPLACE INTO result_cache "
                "(key, target, scope, payload, fetched_at) VALUES (?, ?, ?, ?, ?)",
                (key, target.lower(), scope, json.dumps(payload), int(time.time())),
            )
            conn.commit()
        finally:
            conn.close()
    except Exception:
        pass


def sweep() -> None:
    """Delete entries older than _SWEEP_AGE. Called once at app startup."""
    cutoff = int(time.time()) - _SWEEP_AGE
    try:
        conn = _open()
        try:
            conn.execute("DELETE FROM result_cache WHERE fetched_at < ?", (cutoff,))
            conn.commit()
        finally:
            conn.close()
    except Exception:
        pass
