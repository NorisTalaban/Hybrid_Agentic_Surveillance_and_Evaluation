"""
cost.py — LLM cost tracking for Crisis Monitor.

CHANGES from original utils.py:
  - Extracted into its own module
  - CostTracker class replaces global state (thread-safe, testable)
  - Global functions preserved as convenience wrappers for backward compat
"""

import threading
from logger import get_logger
from config import (
    COST_SONNET_INPUT, COST_SONNET_OUTPUT,
    COST_HAIKU_INPUT, COST_HAIKU_OUTPUT,
)

_log = get_logger("cost_tracker")


class CostTracker:
    """
    Thread-safe cost tracker.
    Can be used as a standalone instance or via the module-level functions.
    """

    def __init__(self):
        self._total: float = 0.0
        self._lock = threading.Lock()
        self._calls: list[dict] = []

    def estimate(self, model: str, input_tokens: int, output_tokens: int) -> float:
        """Estimate cost for a single LLM call."""
        if "haiku" in model:
            cost = (input_tokens / 1_000_000 * COST_HAIKU_INPUT +
                    output_tokens / 1_000_000 * COST_HAIKU_OUTPUT)
        else:
            cost = (input_tokens / 1_000_000 * COST_SONNET_INPUT +
                    output_tokens / 1_000_000 * COST_SONNET_OUTPUT)
        return round(cost, 6)

    def track(self, model: str, input_tokens: int, output_tokens: int,
              label: str = "") -> float:
        """Record a cost entry. Thread-safe."""
        cost = self.estimate(model, input_tokens, output_tokens)
        with self._lock:
            self._total += cost
            self._calls.append({
                "model": model,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "cost": cost,
                "label": label,
            })
        _log.debug(
            f"  Cost [{label}]: ${cost:.4f} "
            f"({input_tokens}in + {output_tokens}out) | "
            f"Run total: ${self._total:.4f}"
        )
        return cost

    def reset(self):
        """Reset all tracked costs."""
        with self._lock:
            self._total = 0.0
            self._calls.clear()

    @property
    def total(self) -> float:
        return round(self._total, 4)

    @property
    def call_count(self) -> int:
        return len(self._calls)

    def summary(self) -> dict:
        """Return a summary of costs by label."""
        by_label: dict[str, float] = {}
        with self._lock:
            for c in self._calls:
                lbl = c["label"] or "unknown"
                by_label[lbl] = by_label.get(lbl, 0.0) + c["cost"]
        return {"total": self.total, "calls": self.call_count, "by_label": by_label}


# ── Global instance + backward-compatible functions ───────────────────────────

_default = CostTracker()


def estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    return _default.estimate(model, input_tokens, output_tokens)


def track(model: str, input_tokens: int, output_tokens: int, label: str = "") -> float:
    return _default.track(model, input_tokens, output_tokens, label=label)


def reset():
    _default.reset()


def get_run_cost() -> float:
    return _default.total
