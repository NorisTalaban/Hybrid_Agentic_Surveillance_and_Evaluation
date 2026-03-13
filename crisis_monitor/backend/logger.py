"""
logger.py — Centralized logging for Crisis Monitor.

Log files are consolidated into 3 per day:
  - pipeline_YYYYMMDD.log  → collector, classifier, matcher, connector, validators A/B
  - analysis_YYYYMMDD.log  → analyst, verifier, scanner, validator_c, seed_writer
  - system_YYYYMMDD.log    → cost_tracker, rag_retriever, run, bootstrap, diagnostic

Each logger still has its own name in the log lines (e.g. "[INFO] classifier — ...")
so you can grep/filter by agent. But they all write to the same file.

Rotation: max 10MB per file, 5 backups kept.
"""

import logging
import os
import sys
from datetime import datetime
from logging.handlers import RotatingFileHandler

_LOG_DIR = "logs"
os.makedirs(_LOG_DIR, exist_ok=True)

_FMT = logging.Formatter(
    "[%(asctime)s] %(levelname)-8s %(name)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)

# ── Log file mapping ─────────────────────────────────────────────────────────
# Which consolidated file each logger writes to

_LOG_GROUPS = {
    # Pipeline agents (every 6h)
    "collector":    "pipeline",
    "classifier":   "pipeline",
    "matcher":      "pipeline",
    "connector":    "pipeline",
    "validator_a":  "pipeline",
    "validator_b":  "pipeline",

    # Analysis agents (daily / weekly / monthly)
    "analyst":      "analysis",
    "verifier":     "analysis",
    "scanner":      "analysis",
    "validator_c":  "analysis",
    "seed_writer":  "analysis",

    # System / infrastructure
    "cost_tracker":   "system",
    "rag_retriever":  "system",
    "run":            "system",
    "bootstrap":      "system",
    "diagnostic":     "system",
    "repair_countries": "system",
    "supervisor":     "system",   # FIX-20: supervisor was missing from mapping
}

# Cache file handlers so multiple loggers share the same handler
_file_handlers: dict[str, RotatingFileHandler] = {}


def _get_file_handler(group: str) -> RotatingFileHandler:
    """Get or create a shared file handler for a log group."""
    today = datetime.now().strftime("%Y%m%d")
    key = f"{group}_{today}"

    if key not in _file_handlers:
        log_file = os.path.join(_LOG_DIR, f"{group}_{today}.log")
        fh = RotatingFileHandler(
            log_file,
            maxBytes=10 * 1024 * 1024,  # 10 MB
            backupCount=5,
            encoding="utf-8",
        )
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(_FMT)
        _file_handlers[key] = fh

    return _file_handlers[key]


def get_logger(name: str) -> logging.Logger:
    """
    Get or create a named logger.

    Console: INFO level (per-logger name visible)
    File:    DEBUG level, written to consolidated group file
    """
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger

    logger.setLevel(logging.DEBUG)

    # Console handler — INFO level
    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.INFO)
    ch.setFormatter(_FMT)
    logger.addHandler(ch)

    # File handler — shared by log group
    group = _LOG_GROUPS.get(name, "system")
    fh = _get_file_handler(group)
    logger.addHandler(fh)

    return logger
