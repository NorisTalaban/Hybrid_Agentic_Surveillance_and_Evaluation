"""
config.py — All constants for Crisis Monitor
"""

import os
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

# ── API Keys ────────────────────────────────────────────────────────────────
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
GNEWS_API_KEY     = os.getenv("GNEWS_API_KEY")
SUPABASE_URL      = os.getenv("SUPABASE_URL")
SUPABASE_KEY      = os.getenv("SUPABASE_KEY")

# ── Models ───────────────────────────────────────────────────────────────────
MODEL_SONNET  = "claude-sonnet-4-20250514"
MODEL_HAIKU   = "claude-haiku-4-5-20251001"
MAX_TOKENS    = 8192

# ── Pipeline Frequencies ─────────────────────────────────────────────────────
ENRICHER_INTERVAL_HOURS   = 6
SCANNER_INTERVAL_DAYS     = 7
VERIFIER_INTERVAL_DAYS    = 30
VERIFIER_MAX_PER_DAY      = 3   # FIX V-01: was 5, causes rate limit hits

# ── Scanner / Bootstrap ──────────────────────────────────────────────────────
_YEAR = datetime.now().year  # FIX-10: dynamic year, not hardcoded

BOOTSTRAP_TARGET_CRISES   = 25
BOOTSTRAP_SEARCH_QUERIES  = [
    f"active armed conflicts humanitarian crises world {_YEAR}",
    f"ongoing natural disasters political crises coups {_YEAR}",
    f"active economic crises sanctions trade wars {_YEAR}",
    f"health emergencies epidemics refugee crises {_YEAR}",
    f"current wars military conflicts escalation {_YEAR}",
]

# ── Collector (GNews) ────────────────────────────────────────────────────────
GNEWS_QUERIES = [
    ("war OR conflict OR attack OR strike OR military",       10),
    ("earthquake OR flood OR hurricane OR disaster",          10),
    ("sanctions OR crisis OR protest OR coup OR election",    10),
    ("pandemic OR outbreak OR emergency",                      5),
    ("",                                                      10),
]
GNEWS_LANG            = "en"
GNEWS_RATE_LIMIT_SEC  = 1.5
GNEWS_MAX_DAILY_CALLS = 100

# ── Classifier ───────────────────────────────────────────────────────────────
VALID_CRISIS_TYPES = ["conflict", "disaster", "economic", "political", "health"]
SEVERITY_MIN       = 1
SEVERITY_MAX       = 10

# ── Analyst ──────────────────────────────────────────────────────────────────
ANALYST_SEVERITY_THRESHOLD = 7
ANALYST_MAX_CRISES_PER_RUN = 3
KEY_TIMELINE_MAX_ENTRIES   = 8

# ── Severity Decay ───────────────────────────────────────────────────────────
SEVERITY_DECAY_DAYS_STABLE = 5
SEVERITY_MINIMUM_ACTIVE    = 2

# ── Crisis Status Values ─────────────────────────────────────────────────────
CRISIS_STATUSES = [
    "active", "escalating", "de_escalating", "stable", "resolved"
]

# FIX R-05: map LLM status variants -> canonical DB values
_STATUS_ALIASES = {
    "potentially_de_escalating": "de_escalating",
    "de-escalating":             "de_escalating",
    "deescalating":              "de_escalating",
    "potentially_escalating":    "escalating",
    "worsening":                 "escalating",
    "improving":                 "de_escalating",
    "stagnant":                  "stable",
    "frozen":                    "stable",
    "ended":                     "resolved",
    "inactive":                  "resolved",
    "ongoing":                   "active",
}

def normalize_status(raw: str) -> str:
    """FIX R-05: Normalize any LLM-generated status to a valid DB value."""
    if not raw:
        return "active"
    s = raw.strip().lower()
    if s in CRISIS_STATUSES:
        return s
    if s in _STATUS_ALIASES:
        return _STATUS_ALIASES[s]
    # Fuzzy: if any canonical status is a substring
    for canonical in CRISIS_STATUSES:
        if canonical in s or s in canonical:
            return canonical
    return "active"  # safe default

# ── Connection Types ─────────────────────────────────────────────────────────
CONNECTION_TYPES = [
    "military_attack", "sanction", "trade_cut", "aid",
    "alliance", "disruption", "refugee_flow", "diplomatic_break"
]

# ── Validator C ──────────────────────────────────────────────────────────────
VALIDATOR_C_RECENCY_DAYS  = 90
VALIDATOR_C_BATCH_SIZE    = 25

# ── RAG ──────────────────────────────────────────────────────────────────────
RAG_MAX_CHUNKS_ANALYST  = 4
RAG_MAX_CHUNKS_SCANNER  = 3
RAG_MAX_CHUNKS_VERIFIER = 3

# ── Cost Tracking ($ per 1M tokens) ─────────────────────────────────────────
COST_SONNET_INPUT   = 3.0
COST_SONNET_OUTPUT  = 15.0
COST_HAIKU_INPUT    = 0.8
COST_HAIKU_OUTPUT   = 4.0