"""
db.py — Supabase client management for Crisis Monitor.

CHANGES from original utils.py:
  - Extracted into its own module
  - Added reconnection support: if the client errors out, it can be reset
  - Added health_check() to verify connectivity
  - FIX-08: added with_retry() helper for transient connection errors
"""

import time
import threading
from supabase import create_client, Client
from config import SUPABASE_URL, SUPABASE_KEY
from logger import get_logger

_log = get_logger("db")
_lock = threading.Lock()
_client: Client | None = None


def get_client() -> Client:
    """Get or create the Supabase client. Thread-safe."""
    global _client
    if _client is not None:
        return _client

    with _lock:
        if _client is not None:
            return _client
        if not SUPABASE_URL or not SUPABASE_KEY:
            raise RuntimeError("SUPABASE_URL and SUPABASE_KEY must be set in .env")
        _client = create_client(SUPABASE_URL, SUPABASE_KEY)
        _log.debug("Supabase client created")
        return _client


def reset_client():
    """Force-reset the client (useful after connection errors)."""
    global _client
    with _lock:
        _client = None
        _log.info("Supabase client reset — will reconnect on next call")


def health_check() -> bool:
    """Quick connectivity check. Returns True if DB is reachable."""
    try:
        db = get_client()
        db.table("crises").select("id", count="exact").limit(1).execute()
        return True
    except Exception as e:
        _log.error(f"Health check failed: {e}")
        return False


def with_retry(fn, max_attempts: int = 3, delay: float = 2.0):
    """
    FIX-08: Execute a DB callable with automatic retry on transient errors.
    Resets the Supabase client between attempts to force reconnection.

    Usage:
        result = with_retry(lambda: get_client().table("crises").select("*").execute())
    """
    last_exc = None
    for attempt in range(max_attempts):
        try:
            return fn()
        except Exception as e:
            last_exc = e
            if attempt < max_attempts - 1:
                _log.warning(f"DB error (attempt {attempt + 1}/{max_attempts}): {e} — retrying in {delay * (attempt + 1):.0f}s")
                reset_client()
                time.sleep(delay * (attempt + 1))
    raise last_exc
