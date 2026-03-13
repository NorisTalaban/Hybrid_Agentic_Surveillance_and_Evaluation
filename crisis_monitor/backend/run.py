"""
run.py — Manual entry point for all Crisis Monitor pipelines.

Usage:
    python run.py collect      <- Agent 01: fetch news from GNews API
    python run.py classify     <- Agent 02: classify articles into crisis events
    python run.py match        <- Agent 03: link events to existing crises
    python run.py connect      <- Agent 04: detect country-to-country relationships
    python run.py analyze      <- Agent 05: deep analysis for severity >= 7
    python run.py verify       <- Agent 06: monthly status check via web search
    python run.py scan         <- Agent 00: weekly web search for new crises + connect
    python run.py supervise    <- Agent 07: system audit + pattern analysis

    python run.py pipeline     <- collect + classify + match + connect (every 6h)
    python run.py all          <- pipeline + analyze + verify (full run)
    python run.py full         <- pipeline + analyze + verify + supervise
"""

import os
import sys
from datetime import datetime, timezone
from utils import get_logger, reset as reset_cost, get_run_cost, RunTracker

log = get_logger("run")
os.makedirs("logs", exist_ok=True)


# ── Individual agents ─────────────────────────────────────────────────────────

def run_collect():
    """Agent 01 -- Collector: fetch news articles from GNews."""
    _header("COLLECT (Agent 01: GNews)")
    reset_cost()
    from agents.agent_01_collector import GNewsCollector

    with RunTracker("collector") as rt:
        count = GNewsCollector().run()
        rt.output_count = count or 0
        rt.cost_usd = get_run_cost()

    log.info(f"Collected {count} new articles.")
    _log_cost()
    return count


def run_classify():
    """Agent 02 -- Classifier: classify raw articles into crisis events."""
    _header("CLASSIFY (Agent 02: Classifier)")
    reset_cost()
    from agents.agent_02_classifier import ClassifierAgent

    with RunTracker("classifier") as rt:
        ClassifierAgent().run()
        rt.cost_usd = get_run_cost()

    _log_cost()


def run_match():
    """Agent 03 -- Matcher: link events to existing crises or create new ones."""
    _header("MATCH (Agent 03: Matcher)")
    reset_cost()
    from agents.agent_03_matcher import MatcherAgent
    from utils import ValidatorA, ValidatorB

    passed_ids = ValidatorA().run()
    if not passed_ids:
        log.info("Validator A: no events passed. Skipping matcher.")
        _log_cost()
        return

    with RunTracker("matcher", input_count=len(passed_ids)) as rt:
        MatcherAgent().run()
        rt.cost_usd = get_run_cost()

    ValidatorB().run()
    _log_cost()


def run_connect():
    """Agent 04 -- Connector: detect country-to-country relationships."""
    _header("CONNECT (Agent 04: Connector)")
    reset_cost()
    from agents.agent_04_connector import ConnectorAgent

    with RunTracker("connector") as rt:
        ConnectorAgent().run()
        rt.cost_usd = get_run_cost()

    _log_cost()


def run_analyze():
    """Agent 05 -- Analyst: deep analysis for high-severity crises."""
    _header("ANALYZE (Agent 05: Analyst)")
    reset_cost()
    from agents.agent_05_analyst import AnalystAgent

    with RunTracker("analyst") as rt:
        AnalystAgent().run()
        rt.cost_usd = get_run_cost()

    _log_cost()


def run_verify():
    """Agent 06 -- Verifier: monthly status check via web search."""
    _header("VERIFY (Agent 06: Verifier)")
    reset_cost()
    from agents.agent_06_verifier import VerifierAgent

    with RunTracker("verifier") as rt:
        VerifierAgent().run()
        rt.cost_usd = get_run_cost()

    _log_cost()


def run_scan():
    """Agent 00 -- Scanner: weekly web search for new crises + Connector."""
    _header("SCAN (Agent 00: Scanner)")
    reset_cost()
    from agents.agent_00_scanner import ScannerAgent
    from agents.agent_04_connector import ConnectorAgent

    with RunTracker("scanner") as rt:
        scanner_ok = ScannerAgent(mode="weekly").run()
        rt.cost_usd = get_run_cost()

    if scanner_ok:
        log.info("")
        _header("CONNECT (post-scan)")
        with RunTracker("connector") as rt:
            ConnectorAgent().run()
            rt.cost_usd = get_run_cost()
    else:
        log.info("Scanner found no new crises — skipping Connector.")

    _log_cost()


def run_supervise():
    """Agent 07 -- Supervisor: system audit + pattern analysis."""
    _header("SUPERVISE (Agent 07: Supervisor)")
    reset_cost()
    from agents.agent_07_supervisor import SupervisorAgent
    SupervisorAgent().run()
    _log_cost()


# ── Combined pipelines ────────────────────────────────────────────────────────

def _pipeline_no_reset():
    """Core pipeline: collect -> classify -> match -> connect."""
    _header("PIPELINE: collect -> classify -> match -> connect")

    from agents.agent_01_collector import GNewsCollector
    from agents.agent_02_classifier import ClassifierAgent
    from agents.agent_03_matcher import MatcherAgent
    from agents.agent_04_connector import ConnectorAgent
    from utils import ValidatorA, ValidatorB, get_client

    db = get_client()

    with RunTracker("collector") as rt:
        new_articles = GNewsCollector().run()
        rt.output_count = new_articles or 0
        rt.cost_usd = get_run_cost()

    if new_articles == 0:
        log.info("No new articles. Pipeline done early.")
        return

    with RunTracker("classifier", input_count=new_articles) as rt:
        ClassifierAgent().run()
        rt.cost_usd = get_run_cost()
        # Count classified events created this run
        try:
            res = db.table("classified_events").select("id", count="exact").is_("crisis_id", "null").execute()
            rt.output_count = res.count or 0
        except Exception:
            pass

    passed_ids = ValidatorA().run()
    if not passed_ids:
        log.info("Validator A: no events passed. Stopping.")
        return

    with RunTracker("matcher", input_count=len(passed_ids)) as rt:
        MatcherAgent().run()
        rt.cost_usd = get_run_cost()
        # Count crises updated/created in last 5 minutes
        try:
            from datetime import datetime, timezone, timedelta
            since = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
            res = db.table("crises").select("id", count="exact").gte("last_updated", since).execute()
            rt.output_count = res.count or 0
        except Exception:
            pass

    ValidatorB().run()

    with RunTracker("connector") as rt:
        ConnectorAgent().run()
        rt.cost_usd = get_run_cost()
        # Count active connections
        try:
            res = db.table("connections").select("id", count="exact").eq("active", True).execute()
            rt.output_count = res.count or 0
        except Exception:
            pass


def run_pipeline():
    """Run the full enrichment pipeline (every 6h)."""
    reset_cost()
    _pipeline_no_reset()
    _log_cost()


def run_all():
    """Run pipeline + analyze + verify (full run)."""
    _header("FULL RUN")
    reset_cost()

    _pipeline_no_reset()

    log.info("")
    _header("ANALYZE (Agent 05: Analyst)")
    with RunTracker("analyst") as rt:
        from agents.agent_05_analyst import AnalystAgent
        agent = AnalystAgent()
        agent.run()
        rt.input_count  = len(agent.target_crises)
        rt.output_count = len(agent.target_crises)
        rt.cost_usd = get_run_cost()

    log.info("")
    _header("VERIFY (Agent 06: Verifier)")
    with RunTracker("verifier") as rt:
        from agents.agent_06_verifier import VerifierAgent
        agent = VerifierAgent()
        agent.run()
        rt.input_count  = len(agent.stale_crises)
        rt.output_count = len(agent.stale_crises)
        rt.cost_usd = get_run_cost()

    log.info(f"\nFull run complete | Total cost: ${get_run_cost():.4f}")


def run_full():
    """Run pipeline + analyze + verify + supervise (everything)."""
    _header("COMPLETE RUN (all agents)")
    reset_cost()

    _pipeline_no_reset()

    log.info("")
    _header("ANALYZE (Agent 05: Analyst)")
    with RunTracker("analyst") as rt:
        from agents.agent_05_analyst import AnalystAgent
        agent = AnalystAgent()
        agent.run()
        rt.input_count  = len(agent.target_crises)
        rt.output_count = len(agent.target_crises)  # each analyzed crisis = 1 output
        rt.cost_usd = get_run_cost()

    log.info("")
    _header("VERIFY (Agent 06: Verifier)")
    with RunTracker("verifier") as rt:
        from agents.agent_06_verifier import VerifierAgent
        agent = VerifierAgent()
        agent.run()
        rt.input_count  = len(agent.stale_crises)
        rt.output_count = len(agent.stale_crises)  # each verified crisis = 1 output
        rt.cost_usd = get_run_cost()

    log.info("")
    _header("SUPERVISE (Agent 07: Supervisor)")
    from agents.agent_07_supervisor import SupervisorAgent
    SupervisorAgent().run()

    log.info(f"\nComplete run done | Total cost: ${get_run_cost():.4f}")


# ── Helpers ───────────────────────────────────────────────────────────────────

def _now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

def _header(title):
    log.info("=" * 60)
    log.info(f"  {title} -- {_now()}")
    log.info("=" * 60)

def _log_cost():
    log.info(f"Cost this run: ${get_run_cost():.4f}")


# ── Command map ───────────────────────────────────────────────────────────────

COMMANDS = {
    "collect":   run_collect,
    "classify":  run_classify,
    "match":     run_match,
    "connect":   run_connect,
    "analyze":   run_analyze,
    "verify":    run_verify,
    "scan":      run_scan,
    "supervise": run_supervise,
    "pipeline":  run_pipeline,
    "all":       run_all,
    "full":      run_full,
}

if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] not in COMMANDS:
        print(__doc__)
        sys.exit(1)
    COMMANDS[sys.argv[1]]()
