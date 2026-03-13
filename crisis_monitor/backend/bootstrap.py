"""
bootstrap.py — One-time setup: seeds the DB with 20-25 active crises.
Run ONCE on day 0.

Pipeline: Scanner → ValidatorC → SeedWriter → Connector
(Scanner no longer calls Connector internally — we call it explicitly here)

CHANGES:
  - Explicit ConnectorAgent.run() call after Scanner completes
  - Better error handling: Scanner failure doesn't skip logging
"""

import os
from datetime import datetime, timezone
from utils import get_logger, reset as reset_cost, get_run_cost, get_client
from agents.agent_00_scanner import ScannerAgent
from agents.agent_04_connector import ConnectorAgent

log = get_logger("bootstrap")
os.makedirs("logs", exist_ok=True)


def run():
    start = datetime.now(timezone.utc)
    log.info("=" * 60)
    log.info("  CRISIS MONITOR — BOOTSTRAP")
    log.info("  Pipeline: Scanner + ValidatorC + SeedWriter + Connector")
    log.info("=" * 60)
    reset_cost()

    db = get_client()
    existing = db.table("crises").select("id", count="exact").execute()
    if existing.count and existing.count > 0:
        log.warning(f"Database already has {existing.count} crises. Bootstrap skipped.")
        log.warning("To re-bootstrap, truncate the crises table first.")
        return

    log.info("\n[1/2] Scanner: searching, validating and seeding DB...")
    scanner_ok = ScannerAgent(mode="bootstrap").run()

    if scanner_ok:
        log.info("\n[2/2] Connector: detecting country-to-country relationships...")
        ConnectorAgent().run()
    else:
        log.warning("Scanner failed — skipping Connector.")

    elapsed     = (datetime.now(timezone.utc) - start).total_seconds()
    result      = db.table("crises").select("id", count="exact").execute()
    connections = db.table("connections").select("id", count="exact").eq("active", True).execute()

    log.info(f"\n{'=' * 60}")
    log.info(f"  Bootstrap complete in {elapsed:.0f}s | Cost: ${get_run_cost():.4f}")
    log.info(f"  Crises in database:  {result.count}")
    log.info(f"  Active connections:  {connections.count}")
    log.info(f"{'=' * 60}")


if __name__ == "__main__":
    run()
