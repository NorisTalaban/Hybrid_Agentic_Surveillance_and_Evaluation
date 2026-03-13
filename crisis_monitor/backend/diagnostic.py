"""
diagnostic.py — Health check for Crisis Monitor.

Usage:  python diagnostic.py
"""

import os
from datetime import datetime, timezone, timedelta
from collections import Counter
from utils import get_client, get_logger

log = get_logger("diagnostic")
os.makedirs("logs", exist_ok=True)

TABLES = [
    "raw_articles", "cm_collection_log", "classified_events",
    "crises", "crisis_events", "connections", "analyses",
    "key_timeline", "country_coords", "verification_log", "validation_errors",
    "cm_agent_runs", "cm_supervisor_log",  # FIX-13: added monitoring tables
]


def run():
    log.info("=" * 60)
    log.info("  CRISIS MONITOR — DIAGNOSTIC")
    log.info("=" * 60)

    db     = get_client()
    all_ok = True

    log.info("\n📊 TABLE COUNTS:")
    for table in TABLES:
        try:
            result = db.table(table).select("id", count="exact").execute()
            log.info(f"  {table:<25} {result.count or 0:>6} rows")
        except Exception as e:
            log.error(f"  {table:<25} ERROR: {e}")
            all_ok = False

    log.info("\n🌍 CRISIS STATUS:")
    try:
        result   = db.table("crises").select("status, severity").execute()
        statuses = Counter(r["status"] for r in (result.data or []))
        for status, count in sorted(statuses.items()):
            log.info(f"  {status:<20} {count}")
    except Exception as e:
        log.error(f"  Could not load crises: {e}")

    log.info("\n⏱ RECENT RUNS:")
    try:
        result = (db.table("cm_collection_log")
                  .select("run_type, collected_at, articles_count, cost_estimate")
                  .order("collected_at", desc=True)
                  .limit(5)
                  .execute())
        for r in (result.data or []):
            log.info(f"  [{r['run_type']:<10}] {r['collected_at'][:16]}  "
                     f"{r['articles_count']:>4} articles  ${r.get('cost_estimate', 0):.4f}")
    except Exception as e:
        log.error(f"  Could not load collection log: {e}")

    log.info("\n⚠ UNRESOLVED VALIDATION ERRORS:")
    try:
        result = (db.table("validation_errors")
                  .select("validator, check_name, severity", count="exact")
                  .eq("resolved", False)
                  .execute())
        if result.count:
            by_check = Counter(f"{r['validator']}:{r['check_name']}" for r in (result.data or []))
            for k, v in sorted(by_check.items(), key=lambda x: -x[1]):
                log.info(f"  {k:<40} {v}")
        else:
            log.info("  No unresolved errors ✓")
    except Exception as e:
        log.error(f"  Could not load validation errors: {e}")

    log.info("\n🔍 CRISES DUE FOR VERIFICATION:")
    try:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
        result = (db.table("crises")
                  .select("name, last_verified")
                  .neq("status", "resolved")
                  .or_(f"last_verified.is.null,last_verified.lt.{cutoff}")
                  .execute())
        count = len(result.data or [])
        log.info(f"  {count} crises due")
        for r in (result.data or [])[:5]:
            log.info(f"    - {r['name']} (last: {r.get('last_verified', 'never')})")
    except Exception as e:
        log.error(f"  Could not check verification: {e}")

    log.info("\n🧠 CRISES DUE FOR ANALYSIS (severity >= 7, new events):")
    try:
        result = (db.table("crises")
                  .select("name, severity, last_event_at, status")
                  .gte("severity", 7)
                  .neq("status", "resolved")
                  .order("severity", desc=True)
                  .execute())
        candidates = result.data or []
        log.info(f"  {len(candidates)} high-severity crises total")
        for c in candidates[:5]:
            last = c.get("last_event_at", "n/a")
            log.info(f"    - {c['name']} (sev={c['severity']}, last_event={last[:10] if last and last != 'n/a' else 'n/a'})")
    except Exception as e:
        log.error(f"  Could not check analyst queue: {e}")

    log.info("\n🔗 ACTIVE CONNECTIONS:")
    try:
        result = db.table("connections").select("relation_type").eq("active", True).execute()
        types  = Counter(r["relation_type"] for r in (result.data or []))
        for t, v in sorted(types.items(), key=lambda x: -x[1]):
            log.info(f"  {t:<25} {v}")
    except Exception as e:
        log.error(f"  Could not load connections: {e}")

    log.info("\n🤖 RECENT AGENT RUNS:")
    try:
        result = (db.table("cm_agent_runs")
                  .select("agent, run_at, status, duration_ms, cost_usd, error_msg")
                  .order("run_at", desc=True)
                  .limit(10)
                  .execute())
        for r in (result.data or []):
            status_icon = "✓" if r["status"] == "success" else "✗"
            dur = f"{r['duration_ms']}ms" if r.get("duration_ms") else "n/a"
            log.info(f"  {status_icon} [{r['agent']:<12}] {r['run_at'][:16]}  "
                     f"{dur:<10}  ${float(r.get('cost_usd') or 0):.4f}"
                     + (f"  ERR: {r['error_msg'][:60]}" if r.get("error_msg") else ""))
    except Exception as e:
        log.error(f"  Could not load agent runs: {e}")

    log.info(f"\n{'=' * 60}")
    log.info(f"  Status: {'✓ OK' if all_ok else '✗ ISSUES FOUND'}")
    log.info(f"{'=' * 60}")
    return all_ok


if __name__ == "__main__":
    run()
