"""
agents/agent_05_analyst.py — Agent 05: ANALYST (FIXED)
Deep analysis + key_timeline for high-severity crises (severity >= 7).
Model: Sonnet. Max 3 crises per run.

FIX 1: skip crises not updated since last analysis (avoids unnecessary re-analysis)
FIX 2: this agent runs via 'python run.py analyst' (every 24h), NOT in the enricher pipeline

RAG: injects relevant academic chunks (escalation theory, crowd psychology)
     into the system prompt via rag_retriever.get_rag_context()
"""

import uuid
import json
from datetime import datetime, timezone
from agents.base_agent import BaseAgent
from utils import get_rag_context
from config import MODEL_SONNET, ANALYST_SEVERITY_THRESHOLD, ANALYST_MAX_CRISES_PER_RUN, KEY_TIMELINE_MAX_ENTRIES, RAG_MAX_CHUNKS_ANALYST
from utils import get_client
from utils import get_logger

log = get_logger("analyst")

_BASE_SYSTEM_PROMPT = f"""You are a senior geopolitical and crisis analyst with deep expertise.
You receive detailed information about a high-severity active crisis.

Produce a comprehensive analysis with this exact JSON structure:
{{
  "crisis_id": "uuid",
  "analysis_text": "3-5 paragraph deep analysis of current situation, dynamics, and outlook",
  "evolutions": [
    {{
      "scenario": "Escalation to regional war",
      "probability": "medium",
      "description": "2-3 sentences explaining this scenario"
    }}
  ],
  "precedents": [
    {{
      "event": "Rwandan Genocide 1994",
      "year": 1994,
      "similarity": "Early warning signs ignored, ethnic tensions exploited"
    }}
  ],
  "key_actors": ["Russia", "NATO", "UN Security Council"],
  "watch_list": ["Civilian evacuation corridors", "Nuclear plant safety"],
  "key_timeline": [
    {{
      "date": "YYYY-MM-DD",
      "title": "Short turning point title",
      "significance": "Why this moment changed the crisis trajectory",
      "severity_impact": "-> 9"
    }}
  ]
}}

Key timeline rules:
  - Max {KEY_TIMELINE_MAX_ENTRIES} entries. Only TURNING POINTS, not every event.
  - Each entry must explain WHY it matters to the crisis trajectory.
  - Sort chronologically.

When academic frameworks are provided below, USE them explicitly:
  - Reference relevant escalation models, warning sign categories, or crisis stages in analysis_text
  - Use them to justify evolution scenarios and precedents
  - Do NOT just list them — integrate them into your reasoning.

Return ONLY valid JSON. No preamble."""


def _build_system_prompt(crisis: dict) -> str:
    extra_kw = []
    if crisis.get("summary"):
        summary_words = crisis["summary"].lower().split()
        extra_kw = [w for w in summary_words if len(w) > 5][:10]
    if crisis.get("type"):
        extra_kw.append(crisis["type"])

    rag_context = get_rag_context(
        agent="analyst",
        crisis_type=crisis.get("type", ""),
        status=crisis.get("status", "active"),
        extra_keywords=extra_kw,
        max_chunks=RAG_MAX_CHUNKS_ANALYST,
    )

    if rag_context:
        return _BASE_SYSTEM_PROMPT + "\n\n" + rag_context
    return _BASE_SYSTEM_PROMPT


class AnalystAgent(BaseAgent):

    def __init__(self):
        super().__init__(model=MODEL_SONNET, agent_name="analyst")
        self.db            = get_client()
        self.target_crises = []

    def check_data(self) -> bool:
        # ── FIX 1: select only crises updated AFTER last analysis ──────
        # Carica le crisi ad alta severità
        result = (self.db.table("crises")
                  .select("*")
                  .gte("severity", ANALYST_SEVERITY_THRESHOLD)
                  .neq("status", "resolved")
                  .order("severity", desc=True)
                  .execute())
        candidates = result.data or []

        if not candidates:
            return False

        # For each candidate, check if it has already been analyzed
        # and if there are no new events since last analysis
        crises_needing_analysis = []
        for crisis in candidates:
            if self._needs_analysis(crisis):
                crises_needing_analysis.append(crisis)
            if len(crises_needing_analysis) >= ANALYST_MAX_CRISES_PER_RUN:
                break

        self.target_crises = crises_needing_analysis
        return len(self.target_crises) > 0

    def _needs_analysis(self, crisis: dict) -> bool:
        """
        Returns True if the crisis has had events AFTER the last analysis,
        or if it has never been analyzed.
        """
        crisis_id = crisis["id"]
        last_event_at = crisis.get("last_event_at")

        # Check the last analysis for this crisis
        try:
            result = (self.db.table("analyses")
                      .select("created_at")
                      .eq("crisis_id", crisis_id)
                      .order("created_at", desc=True)
                      .limit(1)
                      .execute())
            analyses = result.data or []
        except Exception:
            return True  # if read fails, analyze anyway

        # Never analyzed -> analyze
        if not analyses:
            log.debug(f"  {crisis['name']}: never analyzed -> included")
            return True

        last_analyzed_at = analyses[0]["created_at"]

        # No event recorded -> skip
        if not last_event_at:
            log.debug(f"  {crisis['name']}: no last_event_at -> skip")
            return False

        # If there are new events after last analysis -> analyze
        try:
            dt_event    = datetime.fromisoformat(last_event_at.replace("Z", "+00:00"))
            dt_analyzed = datetime.fromisoformat(last_analyzed_at.replace("Z", "+00:00"))
            has_new_events = dt_event > dt_analyzed
        except (ValueError, TypeError):
            has_new_events = last_event_at > last_analyzed_at  # fallback to string compare
        if has_new_events:
            log.debug(f"  {crisis['name']}: new events ({last_event_at} > {last_analyzed_at}) -> inclusa")
        else:
            log.debug(f"  {crisis['name']}: no new events -> skip")
        return has_new_events

    def run(self) -> bool:
        if not self.check_data():
            log.info("[analyst] No high-severity crises need analysis.")
            return False

        log.info(f"[analyst] Analyzing {len(self.target_crises)} crises (filtered from candidates)...")
        for crisis in self.target_crises:
            try:
                self._analyze_crisis(crisis)
            except Exception as e:
                log.error(f"Analyst failed for '{crisis.get('name')}': {e}")

        return True

    def _analyze_crisis(self, crisis: dict):
        log.info(f"  Analyzing: {crisis['name']} (severity={crisis['severity']})")

        events      = self._load_events(crisis["id"])
        connections = self._load_connections(crisis["id"])
        timeline    = self._load_timeline(crisis["id"])

        system_prompt = _build_system_prompt(crisis)

        content = f"""Crisis to analyze:
{json.dumps({
    "crisis_id":      crisis["id"],
    "name":           crisis["name"],
    "type":           crisis["type"],
    "status":         crisis["status"],
    "severity":       crisis["severity"],
    "severity_peak":  crisis.get("severity_peak"),
    "countries":      crisis.get("countries"),
    "summary":        crisis.get("summary"),
    "first_event_at": crisis.get("first_event_at"),
    "last_event_at":  crisis.get("last_event_at"),
}, ensure_ascii=False, indent=2)}

Recent events (last 20):
{json.dumps(events, ensure_ascii=False, indent=2)}

Active connections:
{json.dumps(connections, ensure_ascii=False, indent=2)}

Existing key timeline (extend if needed, max {KEY_TIMELINE_MAX_ENTRIES} total):
{json.dumps(timeline, ensure_ascii=False, indent=2)}"""

        raw = self.call_llm([{"role": "user", "content": content}], system=system_prompt)

        try:
            validated = self.validate_output(raw)
            self.save(validated)
        except Exception as e:
            log.error(f"Failed to save analyst output: {e}")

    def build_prompt(self) -> list[dict]:
        return []

    def validate_output(self, raw: str) -> dict:
        import re
        # FIX: Strip markdown fences before any parsing — Sonnet sometimes wraps in ```json
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            cleaned = re.sub(r'^```(?:json)?\s*', '', cleaned)
            cleaned = re.sub(r'\s*```\s*$', '', cleaned)

        # Try parse_json first
        try:
            data = self.parse_json(cleaned)
        except (ValueError, Exception):
            # Extract the first complete JSON object from the response
            json_matches = re.findall(r'\{[\s\S]*\}', cleaned, re.DOTALL)
            data = None
            for candidate in json_matches:
                try:
                    parsed = json.loads(candidate)
                    if isinstance(parsed, dict) and "crisis_id" in parsed:
                        data = parsed
                        break
                except json.JSONDecodeError:
                    for end in range(len(candidate), max(len(candidate) - 200, 0), -1):
                        if candidate[end - 1] == '}':
                            try:
                                parsed = json.loads(candidate[:end])
                                if isinstance(parsed, dict) and "crisis_id" in parsed:
                                    data = parsed
                                    break
                            except json.JSONDecodeError:
                                continue
                    if data:
                        break
            if data is None:
                raise ValueError(f"Could not extract valid JSON from analyst response (first 200): {raw[:200]}")

        if not isinstance(data, dict):
            raise ValueError("Analyst output must be a JSON object")
        for field in ["crisis_id", "analysis_text", "evolutions", "key_timeline"]:
            if field not in data:
                raise ValueError(f"Missing field: {field}")
        return data

    def save(self, output: dict) -> None:
        now       = datetime.now(timezone.utc).isoformat()
        crisis_id = output["crisis_id"]

        try:
            self.db.table("analyses").insert({
                "id":            str(uuid.uuid4()),
                "crisis_id":     crisis_id,
                "analysis_text": output["analysis_text"],
                "evolutions":    output.get("evolutions", []),
                "precedents":    output.get("precedents", []),
                "key_actors":    output.get("key_actors", []),
                "watch_list":    output.get("watch_list", []),
                "created_at":    now,
            }).execute()
        except Exception as e:
            log.error(f"Failed to save analysis: {e}")

        for i, tp in enumerate(output.get("key_timeline", [])[:KEY_TIMELINE_MAX_ENTRIES]):
            self._upsert_timeline_entry(crisis_id, tp, i, now)

    def _load_events(self, crisis_id: str) -> list:
        try:
            result = (self.db.table("crisis_events")
                      .select("event_date, severity_at, status_at, is_escalation, source")
                      .eq("crisis_id", crisis_id)
                      .order("event_date", desc=True)
                      .limit(20)
                      .execute())
            return result.data or []
        except Exception:
            return []

    def _load_connections(self, crisis_id: str) -> list:
        try:
            result = (self.db.table("connections")
                      .select("from_country, to_country, relation_type, strength, description")
                      .eq("crisis_id", crisis_id)
                      .eq("active", True)
                      .execute())
            return result.data or []
        except Exception:
            return []

    def _load_timeline(self, crisis_id: str) -> list:
        try:
            result = (self.db.table("key_timeline")
                      .select("event_date, title, significance, severity_impact, order_index")
                      .eq("crisis_id", crisis_id)
                      .order("order_index", desc=False)
                      .execute())
            return result.data or []
        except Exception:
            return []

    @staticmethod
    def _clean_date(raw: str) -> str | None:
        """Strip annotations like '(projected)' and return a clean ISO date, or None."""
        if not raw:
            return None
        # Remove anything in parentheses and strip whitespace
        import re
        clean = re.sub(r"\s*\(.*?\)", "", str(raw)).strip()
        # Accept YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS...
        if re.match(r"^\d{4}-\d{2}-\d{2}", clean):
            return clean[:10]  # keep only date part for consistency
        return None

    def _upsert_timeline_entry(self, crisis_id: str, tp: dict, order: int, now: str):
        raw_date = tp.get("date")
        clean_date = self._clean_date(raw_date)
        if not clean_date:
            log.warning(f"[analyst] Skipping timeline entry with unparseable date: {raw_date!r}")
            return
        try:
            result = (self.db.table("key_timeline")
                      .select("id")
                      .eq("crisis_id", crisis_id)
                      .eq("event_date", clean_date)
                      .execute())
            if result.data:
                self.db.table("key_timeline").update({
                    "title":           tp.get("title", ""),
                    "significance":    tp.get("significance", ""),
                    "severity_impact": tp.get("severity_impact", ""),
                    "order_index":     order,
                }).eq("id", result.data[0]["id"]).execute()
            else:
                self.db.table("key_timeline").insert({
                    "id":              str(uuid.uuid4()),
                    "crisis_id":       crisis_id,
                    "event_date":      clean_date,
                    "title":           tp.get("title", ""),
                    "significance":    tp.get("significance", ""),
                    "severity_impact": tp.get("severity_impact", ""),
                    "source":          "analyst",
                    "order_index":     order,
                    "created_at":      now,
                }).execute()
        except Exception as e:
            log.warning(f"Failed to upsert timeline entry: {e}")

# ── Pre-save Sonnet validation ─────────────────────────────────────────────────

ANALYST_VALIDATOR_SYSTEM = """You are a geopolitical analysis quality auditor.

You receive a deep analysis of a crisis just produced by an analyst agent.
Evaluate the quality and flag problems.

Check:
  1. analysis_text: Is it substantive (3-5 paragraphs), specific, not generic? Does it cite real dynamics?
  2. evolutions: Are scenarios realistic and grounded? Probabilities reasonable?
  3. precedents: Are historical comparisons actually relevant to THIS crisis?
  4. key_timeline: Are these real turning points, or just events? Are dates plausible?
  5. watch_list: Are these actionable, specific indicators?

Return ONLY a JSON object:
{
  "quality_score": 1-10,
  "approved": true/false,
  "issues": ["list of specific problems found"],
  "corrections": {
    "analysis_text": "corrected version if needed, else null",
    "key_timeline": [...corrected timeline or null],
    "watch_list": [...corrected or null]
  },
  "rejection_reason": "only if approved=false: why this analysis is too poor to save"
}

Approve unless the analysis is genuinely low quality (score < 5).
Return ONLY valid JSON. No preamble."""


def _analyst_pre_save_validate(self, output: dict) -> dict:
    """Sonnet quality audit of analysis before saving."""
    import json as _json
    if not output:
        return output

    try:
        response = self.client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=1500,
            system=ANALYST_VALIDATOR_SYSTEM,
            messages=[{
                "role": "user",
                "content": f"Audit this analysis:\n\n{_json.dumps(output, ensure_ascii=False, indent=2)}"
            }],
        )
        from utils import track
        from config import MODEL_SONNET
        track(MODEL_SONNET, response.usage.input_tokens, response.usage.output_tokens, label="analyst_validator")

        raw = next((b.text for b in response.content if b.type == "text"), "")
        audit = self.parse_json(raw)

        score    = audit.get("quality_score", 10)
        approved = audit.get("approved", True)
        issues   = audit.get("issues", [])
        corr     = audit.get("corrections", {})

        log.info(f"[analyst] Quality score: {score}/10 — {'APPROVED' if approved else 'REJECTED'}")
        for issue in issues:
            log.warning(f"[analyst] Issue: {issue}")

        if not approved:
            raise ValueError(f"Analysis rejected by validator: {audit.get('rejection_reason', 'quality too low')}")

        # Apply corrections if any
        if corr.get("analysis_text"):
            output["analysis_text"] = corr["analysis_text"]
            log.info("[analyst] analysis_text corrected by validator")
        if corr.get("key_timeline"):
            output["key_timeline"] = corr["key_timeline"]
            log.info("[analyst] key_timeline corrected by validator")
        if corr.get("watch_list"):
            output["watch_list"] = corr["watch_list"]
            log.info("[analyst] watch_list corrected by validator")

    except ValueError:
        raise
    except Exception as e:
        log.warning(f"[analyst] pre_save_validate failed: {e} — saving anyway")

    return output

AnalystAgent.pre_save_validate = _analyst_pre_save_validate
