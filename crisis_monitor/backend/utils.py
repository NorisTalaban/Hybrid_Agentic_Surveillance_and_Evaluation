"""
utils.py — Facade module for Crisis Monitor utilities.

This file re-exports everything from the sub-modules so that
existing imports like `from utils import get_client, ValidatorA`
continue to work without changes.

The actual implementation is split across:
  - logger.py       — Logging with rotation
  - cost.py         — LLM cost tracking (thread-safe)
  - db.py           — Supabase client with reconnection
  - geo.py          — Country coordinates and validation
  - rag.py          — RAG retriever for academic knowledge base
  - seed_writer.py  — Writes Scanner crises to DB
  - validators.py   — ValidatorA, ValidatorB, ValidatorC

RunTracker is defined directly here (not a separate module) to avoid
circular imports: it needs db.get_client() and we can import db directly.
"""

# ── Logger ────────────────────────────────────────────────────────────────────
from logger import get_logger

# ── Cost Tracker ──────────────────────────────────────────────────────────────
from cost import estimate_cost, track, reset, get_run_cost

# ── Supabase Client ───────────────────────────────────────────────────────────
from db import get_client, reset_client, health_check, with_retry

# ── Geo ───────────────────────────────────────────────────────────────────────
from geo import get_coords, get_lat_lng, validate_country_code, all_country_codes

# ── RAG Retriever ─────────────────────────────────────────────────────────────
from rag import get_rag_context, get_rag_chunks

# ── Seed Writer ───────────────────────────────────────────────────────────────
from seed_writer import SeedWriter

# ── Validators ────────────────────────────────────────────────────────────────
from validators import ValidatorA, ValidatorB, ValidatorC


# ── Run Tracker ───────────────────────────────────────────────────────────────
import uuid
import time
from datetime import datetime, timezone

_rt_log = get_logger("supervisor")


class RunTracker:
    """
    Context manager that writes one record to `agent_runs` at the end of
    each agent execution — whether it succeeds or raises an exception.

    Usage in any agent:

        from utils import RunTracker, get_run_cost

        with RunTracker("classifier", input_count=len(articles)) as rt:
            # ... agent logic ...
            rt.output_count = len(classified)
            rt.cost_usd     = get_run_cost()
            rt.meta         = {"batches": n_batches}   # optional

    On exception: saves status="error" with error_msg, then re-raises.
    Never suppresses exceptions.

    Requires the `agent_runs` table in Supabase:
        → run agent_runs_migration.sql once in the Supabase SQL editor.
    """

    def __init__(
        self,
        agent: str,
        input_count: int = 0,
        meta: dict | None = None,
    ):
        self.agent         = agent
        self.input_count   = input_count
        self.output_count  = 0
        self.cost_usd      = 0.0
        self.input_tokens  = 0
        self.output_tokens = 0
        self.meta          = meta or {}
        self._start: float | None = None

    def __enter__(self) -> "RunTracker":
        self._start = time.monotonic()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> bool:
        duration_ms = int((time.monotonic() - self._start) * 1000)
        status      = "error" if exc_type else "success"
        error_msg   = str(exc_val)[:500] if exc_val else None

        try:
            # Import from db directly — avoids circular import with utils
            from db import get_client as _get_client
            db = _get_client()
            db.table("cm_agent_runs").insert({
                "id":            str(uuid.uuid4()),
                "agent":         self.agent,
                "run_at":        datetime.now(timezone.utc).isoformat(),
                "status":        status,
                "duration_ms":   duration_ms,
                "input_count":   self.input_count,
                "output_count":  self.output_count,
                "cost_usd":      round(float(self.cost_usd), 6),
                "input_tokens":  self.input_tokens,
                "output_tokens": self.output_tokens,
                "error_msg":     error_msg,
                "meta":          self.meta,
            }).execute()
        except Exception as e:
            # Never let tracking errors hide the real agent error
            _rt_log.warning(f"[run_tracker] Could not save agent run for '{self.agent}': {e}")

        return False  # never suppress exceptions
