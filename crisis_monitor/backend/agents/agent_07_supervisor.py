"""
agents/agent_07_supervisor.py — Agent 07: META-AUDITOR

The validators inside each agent (01-06) catch errors from THAT run.
The Supervisor catches SYSTEM-LEVEL problems OVER TIME.

Flow:
  1. Python — reads agent_runs from the last 30 days, computes per agent:
     - Metriche dell'ultima run
     - Time series of last 10 runs (input/output/cost/status)
     - Trend: error rate, I/O ratio, costo nel tempo
  2. Sonnet — riceve tutto e identifica pattern sistemici:
     - Drift (metriche in calo da N run)
     - Correlazioni anomale tra agenti
     - Validator overload (base prompt da rivedere)
     - Blind spot geografici
     - Prompt recommendations specifiche

No LLM for metrics — Python only.
Una sola chiamata Sonnet per pattern analysis.

Output: cm_supervisor_log + report console
Uso:    python run_supervisor.py
"""

import uuid
import json
from datetime import datetime, timezone, timedelta
from collections import Counter, defaultdict
from agents.base_agent import BaseAgent
from config import MODEL_SONNET
from utils import get_client, get_logger, RunTracker, get_run_cost

log = get_logger("supervisor")


PATTERN_ANALYSIS_PROMPT = """You are a senior ML pipeline reliability engineer analyzing an AI crisis monitoring system.

The system has 7 agents: Scanner → Collector → Classifier → Matcher → Connector → Analyst → Verifier.
Scanner is the first agent (weekly web search for new crises) — if it fails, the pipeline can miss entire crises.
Each agent has an internal Sonnet self-validator that catches per-run errors.
YOUR job is different: find SYSTEMIC patterns across multiple runs that no single run can reveal.

You receive:
- Per-agent metrics for the LAST RUN specifically
- Historical time series (one entry per run, chronological, last 10 runs each)
- 30-day aggregate summaries per agent

Analyze for:

1. DRIFT — Is any metric trending wrong over the last 5+ runs?
   Example: "Classifier avg_severity dropping 6.2→5.8→5.1→4.9→4.6 — systematic under-classification"

2. CORRELATION ANOMALIES — Do agent metrics move together unexpectedly?
   Example: "When collector useful_rate drops below 0.5, matcher output_count spikes — bad input causes hallucinated new crises"

3. VALIDATOR OVERLOAD — Any agent corrected by its validator in >30% of runs?
   Means the base prompt needs fixing, not just catching errors downstream.
   Example: "Connector validator removed connections in 8/10 runs — base prompt generates too many weak connections"

4. COST ANOMALIES — Unexpected cost spikes or creep?

5. COLD START — Does performance drop after gaps between runs?

For each finding, be SPECIFIC and ACTIONABLE. Name exact metrics, quantify drift, suggest exact prompt fix.

Return ONLY a JSON object:
{
  "pipeline_health": "stable|degrading|critical",
  "health_summary": "2-3 sentence executive summary of system health trend",
  "last_run_summary": "1 sentence: was last run normal, better, or worse than recent average?",
  "findings": [
    {
      "type": "drift|correlation|validator_overload|cost_anomaly|cold_start|other",
      "agent": "collector|classifier|matcher|connector|analyst|verifier|cross_pipeline",
      "severity": "low|medium|high|critical",
      "title": "Short title",
      "evidence": "Specific numbers supporting this finding",
      "impact": "What goes wrong if ignored",
      "action": "Specific concrete fix recommended"
    }
  ],
  "agent_trends": {
    "scanner":    {"trend": "improving|stable|degrading", "note": "1 sentence"},
    "collector":  {"trend": "improving|stable|degrading", "note": "1 sentence"},
    "classifier": {"trend": "improving|stable|degrading", "note": "1 sentence"},
    "matcher":    {"trend": "improving|stable|degrading", "note": "1 sentence"},
    "connector":  {"trend": "improving|stable|degrading", "note": "1 sentence"},
    "analyst":    {"trend": "improving|stable|degrading", "note": "1 sentence"},
    "verifier":   {"trend": "improving|stable|degrading", "note": "1 sentence"}
  },
  "prompt_recommendations": [
    {
      "agent": "...",
      "file": "agent_0X_name.py",
      "issue": "what the current prompt does wrong",
      "suggestion": "specific change to make"
    }
  ]
}

Be a rigorous engineer, not a cheerleader. Name problems clearly.
Return ONLY valid JSON. No preamble."""


class SupervisorAgent(BaseAgent):

    def __init__(self):
        super().__init__(model=MODEL_SONNET, agent_name="supervisor")
        self.db  = get_client()
        self.now = datetime.now(timezone.utc)

    def check_data(self)         -> bool: return True
    def build_prompt(self)       -> list: return []
    def validate_output(self, r) -> dict: return {}
    def save(self, v)            -> None: pass

    # ── Entry point ───────────────────────────────────────────────────────────

    def run(self) -> bool:
        log.info("[supervisor] Starting meta-audit...")

        history  = self._load_run_history()
        snapshot = self._load_snapshot()

        log.info(f"[supervisor] Loaded {len(history['all_runs'])} runs | "
                 f"{len(snapshot['crises'])} crises | "
                 f"{len(snapshot['val_errors'])} validation errors (7d)")

        with RunTracker("supervisor", input_count=len(history["all_runs"])) as rt:

            metrics  = self._compute_metrics(history, snapshot)
            log.info("[supervisor] Metrics computed. Calling Sonnet for pattern analysis...")

            analysis = self._analyse_patterns(metrics, history)
            findings = analysis.get("findings", [])
            health   = analysis.get("pipeline_health", "?")
            log.info(f"[supervisor] Health: {health} | {len(findings)} findings | "
                     f"{len(analysis.get('prompt_recommendations', []))} prompt recommendations")

            rt.output_count = len(findings)
            rt.cost_usd     = get_run_cost()

            self._save(metrics, analysis)
            self._print(metrics, analysis)

        log.info("[supervisor] Done.")
        return True

    # ── Load data ─────────────────────────────────────────────────────────────

    def _load_run_history(self) -> dict:
        since_30d = (self.now - timedelta(days=30)).isoformat()
        runs = (self.db.table("cm_agent_runs")
                .select("id,agent,run_at,status,duration_ms,input_count,"
                        "output_count,cost_usd,input_tokens,output_tokens,error_msg,meta")
                .gte("run_at", since_30d)
                .order("run_at", desc=False)
                .execute().data or [])

        by_agent = defaultdict(list)
        for r in runs:
            by_agent[r["agent"]].append(r)

        return {"all_runs": runs, "by_agent": dict(by_agent)}

    def _load_snapshot(self) -> dict:
        since_7d = (self.now - timedelta(days=7)).isoformat()

        crises = (self.db.table("crises")
                  .select("id,status,severity,severity_peak,countries,"
                          "primary_country,lat,lng,event_count,source")
                  .execute().data or [])

        val_errors = (self.db.table("validation_errors")
                      .select("id,validator,severity,resolved,created_at")
                      .gte("created_at", since_7d)
                      .execute().data or [])

        return {"crises": crises, "val_errors": val_errors}

    # ── Compute metrics ───────────────────────────────────────────────────────

    def _compute_metrics(self, history: dict, snapshot: dict) -> dict:
        by_agent = history["by_agent"]
        AGENTS   = ["scanner", "collector", "classifier", "matcher",
                    "connector", "analyst", "verifier"]   # FIX-4: scanner included
        result   = {}

        for agent in AGENTS:
            runs = by_agent.get(agent, [])
            if not runs:
                result[agent] = {"last_run": None, "time_series": [], "summary": {}}
                continue

            last   = runs[-1]
            recent = runs[-10:]

            # Time series
            time_series = []
            for r in recent:
                entry = {
                    "run_at":       r["run_at"],
                    "status":       r["status"],
                    "duration_ms":  r.get("duration_ms"),
                    "input_count":  r.get("input_count"),
                    "output_count": r.get("output_count"),
                    "cost_usd":     float(r.get("cost_usd") or 0),
                    "error_msg":    r.get("error_msg"),
                }
                meta = r.get("meta") or {}
                if isinstance(meta, dict):
                    entry.update({k: v for k, v in meta.items()
                                  if k not in entry and not isinstance(v, (dict, list))})
                time_series.append(entry)

            # 30d aggregate
            total     = len(runs)
            successes = len([r for r in runs if r["status"] == "success"])
            errors    = len([r for r in runs if r["status"] == "error"])
            total_cost   = sum(float(r.get("cost_usd") or 0) for r in runs)
            total_tokens = sum((r.get("input_tokens") or 0) + (r.get("output_tokens") or 0)
                               for r in runs)
            durations = [r["duration_ms"] for r in runs if r.get("duration_ms")]
            avg_dur   = round(sum(durations) / len(durations)) if durations else None

            # Error trend: first half vs second half
            # FIX-5: with fewer than 4 runs, trend is not computable
            if len(runs) < 4:
                error_trend = None
            else:
                mid       = max(len(runs) // 2, 1)
                first_h   = runs[:mid]
                second_h  = runs[mid:]
                err_first  = len([r for r in first_h  if r["status"] == "error"]) / len(first_h)
                err_second = len([r for r in second_h if r["status"] == "error"]) / max(len(second_h), 1)
                error_trend = round(err_second - err_first, 3)

            # I/O ratio trend
            ratios = [
                r["output_count"] / r["input_count"]
                for r in runs
                if r.get("input_count") and r.get("output_count") and r["input_count"] > 0
            ]
            avg_ratio   = round(sum(ratios) / len(ratios), 3) if ratios else None
            ratio_trend = None
            if len(ratios) >= 4:
                half = len(ratios) // 2
                ratio_trend = round(
                    sum(ratios[half:]) / max(len(ratios[half:]), 1) -
                    sum(ratios[:half])  / max(len(ratios[:half]), 1),
                    3
                )

            # Cost trend
            costs = [float(r.get("cost_usd") or 0) for r in runs]
            cost_trend = None
            if len(costs) >= 4:
                half = len(costs) // 2
                cost_trend = round(
                    sum(costs[half:]) / max(len(costs[half:]), 1) -
                    sum(costs[:half])  / max(len(costs[:half]), 1),
                    4
                )

            result[agent] = {
                "last_run":    last,
                "time_series": time_series,
                "summary": {
                    "total_runs":        total,
                    "success_rate":      round(successes / total, 3),
                    "error_count":       errors,
                    "error_trend":       error_trend,
                    "total_cost_usd":    round(total_cost, 4),
                    "total_tokens":      total_tokens,
                    "avg_duration_ms":   avg_dur,
                    "avg_io_ratio":      avg_ratio,
                    "io_ratio_trend":    ratio_trend,
                    "cost_trend":        cost_trend,
                    # FIX-2: last run data for empty output penalty
                    "last_input_count":  last.get("input_count", 0),
                    "last_output_count": last.get("output_count", 0),
                }
            }

        # DB integrity
        crises     = snapshot["crises"]
        val_errors = snapshot["val_errors"]
        total_c    = len(crises)
        anomalies  = (
            len([c for c in crises if not c.get("lat") or not c.get("lng")]) +
            len([c for c in crises if not c.get("countries")]) +
            len([c for c in crises if not c.get("severity")]) +
            len([c for c in crises if (c.get("severity_peak") or 0) < (c.get("severity") or 0)]) +
            len([c for c in crises if c.get("status") == "active" and (c.get("event_count") or 0) == 0])
        )
        hard_fails = len([e for e in val_errors
                          if e.get("severity") == "hard_fail" and not e.get("resolved")])

        result["_integrity"] = {
            "total_crises":    total_c,
            "total_anomalies": anomalies,
            "integrity_rate":  round(max(0, 1 - anomalies / max(total_c * 5, 1)), 3),
            "hard_fails_7d":   hard_fails,
        }

        return result

    # ── Sonnet pattern analysis ───────────────────────────────────────────────

    def _analyse_patterns(self, metrics: dict, history: dict) -> dict:
        AGENTS = ["scanner", "collector", "classifier", "matcher",
                  "connector", "analyst", "verifier"]       # FIX-4: scanner included

        payload = {
            "analysis_date":  self.now.strftime("%Y-%m-%d %H:%M UTC"),
            "total_runs_30d": len(history["all_runs"]),
            "data_integrity": metrics.get("_integrity", {}),
            "agents": {},
        }

        for agent in AGENTS:
            data    = metrics.get(agent, {})
            last    = data.get("last_run") or {}
            summary = data.get("summary", {})
            ts      = data.get("time_series", [])

            payload["agents"][agent] = {
                "last_run": {
                    "status":       last.get("status"),
                    "run_at":       last.get("run_at"),
                    "input_count":  last.get("input_count"),
                    "output_count": last.get("output_count"),
                    "duration_ms":  last.get("duration_ms"),
                    "cost_usd":     float(last.get("cost_usd") or 0),
                    "error_msg":    last.get("error_msg"),
                },
                "30d_summary":     summary,
                "recent_10_runs": [
                    {
                        "run_at":       r["run_at"],
                        "status":       r["status"],
                        "input_count":  r.get("input_count"),
                        "output_count": r.get("output_count"),
                        "cost_usd":     r.get("cost_usd"),
                        # FIX-6: additional data for causal analysis
                        "error_msg":    r.get("error_msg"),
                        "duration_ms":  r.get("duration_ms"),
                        "meta_summary": {k: v for k, v in (r.get("meta") or {}).items()
                                         if not isinstance(v, (dict, list))}
                                        if isinstance(r.get("meta"), dict) else None,
                    }
                    for r in ts
                ],
            }

        try:
            raw = self.call_llm(
                system=PATTERN_ANALYSIS_PROMPT,
                messages=[{
                    "role": "user",
                    "content": (
                        f"Analyze this pipeline run history for systemic patterns:\n\n"
                        f"{json.dumps(payload, ensure_ascii=False, indent=2)}"
                    )
                }],
            )
            result = self.parse_json(raw)
            if isinstance(result, dict) and "findings" in result:
                return result
        except Exception as e:
            log.error(f"[supervisor] Pattern analysis failed: {e}")

        return {
            "pipeline_health": "unknown",
            "health_summary": "Pattern analysis unavailable.",
            "last_run_summary": "",
            "findings": [],
            "agent_trends": {},
            "prompt_recommendations": [],
        }

    # ── Save ──────────────────────────────────────────────────────────────────

    def _summary_to_score(self, summary: dict) -> int | None:
        if not summary:
            return None
        total_runs = summary.get("total_runs", 0)
        if total_runs < 3:
            return None                       # FIX-3: insufficient data → no score

        sr  = summary.get("success_rate", 0)
        et  = summary.get("error_trend")      # FIX-5: can be None now
        ior = summary.get("io_ratio_trend") or 0

        s = sr * 60 + max(0, 1 - abs(et or 0) * 2) * 25 + max(0, min(1, 0.5 + ior)) * 15

        # FIX-2: penalty for output_count == 0 with input_count > 0
        last_in  = summary.get("last_input_count", 0)
        last_out = summary.get("last_output_count", 0)
        if last_in > 0 and last_out == 0:
            s -= 20

        # FIX-2: weight on current io_ratio (not just trend)
        avg_io = summary.get("avg_io_ratio")
        if avg_io is not None and avg_io < 0.1:
            s -= 10

        return max(0, min(100, round(s)))     # FIX-1: removed * 100

    def _save(self, metrics: dict, analysis: dict) -> None:
        pipeline_stats = {}
        for agent in ["scanner", "collector", "classifier", "matcher",
                       "connector", "analyst", "verifier"]:   # FIX-4: scanner included
            data    = metrics.get(agent, {})
            summary = data.get("summary", {})
            trend   = (analysis.get("agent_trends") or {}).get(agent, {})
            runs_count = summary.get("total_runs", 0)

            verdict = trend.get("trend")
            comment = trend.get("note", "")

            # FIX-3: verdict unreliable with fewer than 3 runs
            if runs_count < 3:
                verdict = "insufficient_data"
                comment += " (based on <3 runs — trend unreliable)" if comment else "<3 runs — trend unreliable"

            pipeline_stats[agent] = {
                "score":   self._summary_to_score(summary),
                "metrics": summary,
                "verdict": verdict,
                "comment": comment,
            }

        try:
            self.db.table("cm_supervisor_log").insert({
                "id":                    str(uuid.uuid4()),
                "run_at":                self.now.isoformat(),
                "match_issues":          [],
                "resolution_candidates": [],
                "country_issues":        [],
                "anomalies":             [],
                "pipeline_stats":        pipeline_stats,
                "summary":               analysis.get("health_summary", ""),
                "overall_health":        analysis.get("pipeline_health", "unknown"),
            }).execute()
            log.info("[supervisor] Meta-audit saved.")
        except Exception as e:
            log.error(f"[supervisor] Failed to save: {e}")

    # ── Console report ────────────────────────────────────────────────────────

    def _print(self, metrics: dict, analysis: dict) -> None:
        SEV   = {"low": "·", "medium": "▲", "high": "●", "critical": "■"}
        TREND = {"improving": "↑", "stable": "→", "degrading": "↓"}

        print("\n" + "═" * 68)
        print("  CRISIS MONITOR — PIPELINE META-AUDIT")
        print(f"  {self.now.strftime('%Y-%m-%d %H:%M UTC')}")
        print("═" * 68)

        health = analysis.get("pipeline_health", "?").upper()
        print(f"\n  PIPELINE HEALTH : {health}")
        print(f"  {analysis.get('health_summary', '')}")
        if analysis.get("last_run_summary"):
            print(f"\n  Last run: {analysis['last_run_summary']}")

        # Agent trends
        trends = analysis.get("agent_trends", {})
        if trends:
            print(f"\n  {'─'*64}")
            print("  AGENT TRENDS (30d)")
            for agent, t in trends.items():
                icon = TREND.get(t.get("trend", ""), "?")
                print(f"  {icon} {agent:12}  {t.get('note', '')}")

        # Findings
        findings = analysis.get("findings", [])
        if findings:
            print(f"\n  {'─'*64}")
            print(f"  FINDINGS ({len(findings)})")
            for f in sorted(findings, key=lambda x: ["critical","high","medium","low"].index(x.get("severity","low"))):
                icon = SEV.get(f.get("severity", "low"), "·")
                print(f"\n  {icon} [{f.get('severity','?').upper():8}] {f.get('title','')}")
                print(f"    Agent    : {f.get('agent','?')} ({f.get('type','?')})")
                print(f"    Evidence : {f.get('evidence','')}")
                print(f"    Impact   : {f.get('impact','')}")
                print(f"    Action   : {f.get('action','')}")

        # Prompt recommendations
        recs = analysis.get("prompt_recommendations", [])
        if recs:
            print(f"\n  {'─'*64}")
            print(f"  PROMPT FIXES RECOMMENDED ({len(recs)})")
            for r in recs:
                print(f"\n  → {r.get('file','?')}")
                print(f"    Issue      : {r.get('issue','')}")
                print(f"    Suggestion : {r.get('suggestion','')}")

        # 30d run summary table
        print(f"\n  {'─'*64}")
        print("  30-DAY RUN STATS")
        for agent in ["scanner", "collector", "classifier", "matcher",
                      "connector", "analyst", "verifier"]:   # FIX-4: scanner included
            data = metrics.get(agent, {})
            s    = data.get("summary", {})
            if not s:
                print(f"  {agent:12} — no data")
                continue
            et = s.get("error_trend")
            et_str = "N/A" if et is None else (f"+{et:.2f}" if et > 0 else f"{et:.2f}")  # FIX-5
            print(f"  {agent:12}  "
                  f"runs:{s.get('total_runs','?'):>3}  "
                  f"ok:{s.get('success_rate',0):.0%}  "
                  f"err:{s.get('error_count',0):>2}  "
                  f"err_trend:{et_str}  "
                  f"cost:${s.get('total_cost_usd',0):.3f}")

        integ = metrics.get("_integrity", {})
        if integ:
            print(f"\n  Integrity:{integ.get('integrity_rate',0):.0%}  "
                  f"anomalies:{integ.get('total_anomalies','?')}  "
                  f"hard_fails_7d:{integ.get('hard_fails_7d','?')}")

        print("═" * 68 + "\n")
