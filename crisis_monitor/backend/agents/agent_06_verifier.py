"""
agents/agent_06_verifier.py — Agent 06: VERIFIER
Monthly status check per crisis via web search.
Only uses sources published AFTER last_event_at.

RAG: injects crisis stage frameworks (Fink, PCMP) to improve
     status classification and media_gap assessment.
"""

import time
import uuid
import json
from datetime import datetime, timezone, timedelta
from agents.base_agent import BaseAgent
from utils import get_rag_context
from config import MODEL_SONNET, VERIFIER_INTERVAL_DAYS, VERIFIER_MAX_PER_DAY, RAG_MAX_CHUNKS_VERIFIER
from utils import get_client
from utils import get_logger

log = get_logger("verifier")

WEB_SEARCH_TOOL = {
    "type": "web_search_20250305",
    "name": "web_search",
}

_BASE_SYSTEM_PROMPT = """You are a crisis verification specialist with web search access.

You will receive details about an active crisis that needs status verification.
Search the web for RECENT information about this crisis.

CRITICAL: Only use sources published AFTER the date provided as last_event_at.
Report the publication date of each source you cite.

Return a JSON object:
{
  "crisis_id": "uuid",
  "verification_status": "still_active|resolved|escalated|de_escalated|insufficient_data",
  "current_severity": 7,
  "evidence": "2-3 sentences summarizing what you found",
  "sources": ["https://url1", "https://url2"],
  "new_summary": "Updated 1-2 sentence summary of current situation",
  "media_gap": true/false,
  "source_dates": ["2026-02-15", "2026-02-20"]
}

media_gap = true if crisis appears still active but has little/no recent media coverage.

When academic crisis stage frameworks are provided below, USE them to:
  - Better classify the crisis stage (prodromal / acute / chronic / resolution)
  - Identify warning signals of re-escalation
  - Distinguish between genuine resolution and a media gap (chronic stage)

Return ONLY valid JSON at the end of your response. No preamble."""

VALID_STATUSES = {"still_active", "resolved", "escalated", "de_escalated", "insufficient_data"}


def _build_system_prompt(crisis: dict) -> str:
    """Build verifier system prompt with RAG crisis-stage frameworks."""
    extra_kw = []
    if crisis.get("type"):
        extra_kw.append(crisis["type"])
    if crisis.get("status"):
        extra_kw.append(crisis["status"])
    if crisis.get("status") in ("de_escalating", "stable"):
        extra_kw += ["resolution", "chronic", "media gap", "latent"]
    elif crisis.get("status") in ("escalating", "active"):
        extra_kw += ["acute", "warning signals", "escalation"]

    rag_context = get_rag_context(
        agent="verifier",
        crisis_type=crisis.get("type", ""),
        status=crisis.get("status", "active"),
        extra_keywords=extra_kw,
        max_chunks=RAG_MAX_CHUNKS_VERIFIER,
    )
    if rag_context:
        return _BASE_SYSTEM_PROMPT + "\n\n" + rag_context
    return _BASE_SYSTEM_PROMPT


class VerifierAgent(BaseAgent):

    def __init__(self):
        super().__init__(model=MODEL_SONNET, agent_name="verifier")
        self.db           = get_client()
        self.stale_crises = []

    def check_data(self) -> bool:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=VERIFIER_INTERVAL_DAYS)).isoformat()
        result = (self.db.table("crises")
                  .select("*")
                  .neq("status", "resolved")
                  .or_(f"last_verified.is.null,last_verified.lt.{cutoff}")
                  .order("last_verified", desc=False, nullsfirst=True)
                  .limit(VERIFIER_MAX_PER_DAY)
                  .execute())
        self.stale_crises = result.data or []
        return len(self.stale_crises) > 0

    def run(self) -> bool:
        if not self.check_data():
            log.info("[verifier] No crises due for verification.")
            return False

        log.info(f"[verifier] Verifying {len(self.stale_crises)} crises...")
        for i, crisis in enumerate(self.stale_crises):
            try:
                self._verify_crisis(crisis)
            except Exception as e:
                log.error(f"Verifier failed for '{crisis.get('name')}': {e}")
            # FIX V-01: increased from 25s to 60s to avoid 30k tok/min rate limit
            if i < len(self.stale_crises) - 1:
                log.info("[verifier] Waiting 60s before next verification...")
                time.sleep(60)
        return True

    def _verify_crisis(self, crisis: dict):
        log.info(f"  Verifying: {crisis['name']}")

        system_prompt = _build_system_prompt(crisis)

        prompt = f"""Verify the current status of this crisis:

Name: {crisis['name']}
Type: {crisis['type']}
Current status: {crisis['status']}
Current severity: {crisis['severity']}
Countries: {crisis.get('countries', [])}
Summary: {crisis.get('summary', '')}
Last known event: {crisis.get('last_event_at', 'unknown')}
Crisis ID: {crisis['id']}

IMPORTANT: Only use sources published AFTER {crisis.get('last_event_at', '2026-01-01')}.
Report publication dates of your sources.
Use the crisis stage frameworks in the system prompt to classify the current phase.
Return ONLY valid JSON at the end of your response."""

        raw = self.call_llm(
            [{"role": "user", "content": prompt}],
            system=system_prompt,
            tools=[WEB_SEARCH_TOOL]
        )

        try:
            result = self.validate_output(raw)
            self.save(result, crisis)
        except Exception as e:
            log.error(f"Failed to process verifier output: {e}")

    def build_prompt(self) -> list[dict]:
        return []

    def validate_output(self, raw: str) -> dict:
        import re
        # Try parse_json first
        try:
            data = self.parse_json(raw)
            if isinstance(data, dict) and "verification_status" in data:
                if data["verification_status"] in VALID_STATUSES:
                    return data
        except Exception:
            pass

        # Fallback: extract JSON objects and try each one
        json_matches = re.findall(r'\{[\s\S]*\}', raw, re.DOTALL)
        data = None
        for candidate in reversed(json_matches):
            try:
                parsed = json.loads(candidate)
                if isinstance(parsed, dict) and "verification_status" in parsed:
                    data = parsed
                    break
            except json.JSONDecodeError:
                # Try trimming from the end to find valid JSON boundary
                for end in range(len(candidate), max(len(candidate) - 500, 0), -1):
                    if candidate[end - 1] == '}':
                        try:
                            parsed = json.loads(candidate[:end])
                            if isinstance(parsed, dict) and "verification_status" in parsed:
                                data = parsed
                                break
                        except json.JSONDecodeError:
                            continue
                if data:
                    break

        if data is None:
            raise ValueError(f"Could not extract valid JSON from verifier response (first 200): {raw[:200]}")

        if data.get("verification_status") not in VALID_STATUSES:
            raise ValueError(f"Unknown verification_status: {data.get('verification_status')}")
        return data

    def save(self, result: dict, crisis: dict = None) -> None:
        now       = datetime.now(timezone.utc).isoformat()
        crisis_id = result["crisis_id"]
        vstatus   = result["verification_status"]

        status_map = {
            "still_active":      crisis.get("status", "active"),
            "resolved":          "resolved",
            "escalated":         "escalating",
            "de_escalated":      "de_escalating",
            "insufficient_data": crisis.get("status", "stable"),
        }
        new_status = status_map.get(vstatus, "stable")

        update = {
            "last_verified": now,
            "last_updated":  now,
            "status":        new_status,
            "media_gap":     result.get("media_gap", False),
        }
        if result.get("current_severity"):
            update["severity"] = result["current_severity"]
            # Update severity_peak if new severity exceeds it
            current_peak = crisis.get("severity_peak", 0) or 0
            if result["current_severity"] > current_peak:
                update["severity_peak"] = result["current_severity"]
        if result.get("new_summary"):
            update["summary"] = result["new_summary"]
        if vstatus == "resolved":
            update["resolved_at"] = now

        try:
            self.db.table("crises").update(update).eq("id", crisis_id).execute()
        except Exception as e:
            log.error(f"Failed to update crisis {crisis_id}: {e}")
            return

        try:
            self.db.table("verification_log").insert({
                "id":              str(uuid.uuid4()),
                "crisis_id":       crisis_id,
                "status_before":   crisis.get("status"),
                "status_after":    new_status,
                "severity_before": crisis.get("severity"),
                "severity_after":  result.get("current_severity", crisis.get("severity")),
                "result":          vstatus,
                "evidence":        result.get("evidence", ""),
                "sources":         result.get("sources", []),
                "media_gap":       result.get("media_gap", False),
                "verified_at":     now,
            }).execute()
        except Exception as e:
            log.error(f"Failed to insert verification_log: {e}")

        try:
            self.db.table("crisis_events").insert({
                "id":            str(uuid.uuid4()),
                "crisis_id":     crisis_id,
                "event_id":      None,
                "event_date":    now,
                "severity_at":   result.get("current_severity", crisis.get("severity")),
                "status_at":     new_status,
                "is_escalation": (vstatus == "escalated"),
                "source":        "verifier",
                "created_at":    now,
            }).execute()
        except Exception as e:
            log.error(f"Failed to insert verifier crisis_event: {e}")

        log.info(f"  [OK] {crisis.get('name')}: {crisis.get('status')} -> {new_status} "
                 f"[media_gap={result.get('media_gap')}]")


# ── Pre-save Sonnet validation ─────────────────────────────────────────────────

VERIFIER_VALIDATOR_SYSTEM = """You are a crisis verification auditor.

You receive the output of a verifier agent that just checked the status of a crisis using web search.
Your job: validate the conclusion before it's saved to the database.

Check:
  1. Is the verification_status consistent with the evidence provided?
     (e.g. if evidence says "ceasefire signed", status should be resolved or de_escalated)
  2. Is current_severity realistic given the evidence?
  3. Is the media_gap flag correct?
     (media_gap=true means crisis is real but press stopped covering it)
  4. Are the sources recent enough? (should be after last_event_at)
  5. Is "insufficient_data" being used correctly? (only when truly no info found)

Return ONLY a JSON object:
{
  "approved": true/false,
  "corrected_status": "still_active|resolved|escalated|de_escalated|insufficient_data|null",
  "corrected_severity": 1-10 or null,
  "corrected_media_gap": true/false/null,
  "validation_note": "brief explanation of any corrections or confirmation",
  "rejection_reason": "only if approved=false"
}

If everything checks out, set approved=true and all corrected_* to null.
Return ONLY valid JSON. No preamble."""


def _verifier_pre_save_validate(self, result: dict) -> dict:
    """Sonnet audit of verification result before saving.
    FIX V-02: retries once on rate limit instead of skipping validation."""
    import json as _json
    if not result:
        return result

    for attempt in range(2):  # FIX V-02: retry loop
        try:
            response = self.client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=600,
                system=VERIFIER_VALIDATOR_SYSTEM,
                messages=[{
                    "role": "user",
                    "content": f"Audit this verification result:\n\n{_json.dumps(result, ensure_ascii=False, indent=2)}"
                }],
            )
            from utils import track
            from config import MODEL_SONNET
            track(MODEL_SONNET, response.usage.input_tokens, response.usage.output_tokens, label="verifier_validator")

            raw = next((b.text for b in response.content if b.type == "text"), "")
            audit = self.parse_json(raw)

            approved = audit.get("approved", True)
            note     = audit.get("validation_note", "")

            log.info(f"[verifier] Audit: {'APPROVED' if approved else 'REJECTED'} — {note}")

            if not approved:
                raise ValueError(f"Verification rejected: {audit.get('rejection_reason', 'inconsistent evidence')}")

            # Apply corrections
            if audit.get("corrected_status"):
                old = result.get("verification_status")
                result["verification_status"] = audit["corrected_status"]
                log.info(f"[verifier] Status corrected: {old} → {audit['corrected_status']}")

            if audit.get("corrected_severity") is not None:
                old = result.get("current_severity")
                result["current_severity"] = audit["corrected_severity"]
                log.info(f"[verifier] Severity corrected: {old} → {audit['corrected_severity']}")

            if audit.get("corrected_media_gap") is not None:
                result["media_gap"] = audit["corrected_media_gap"]
                log.info(f"[verifier] media_gap corrected to: {audit['corrected_media_gap']}")

            break  # success — exit retry loop

        except ValueError:
            raise
        except Exception as e:
            if attempt == 0 and "rate_limit" in str(e).lower():
                log.warning(f"[verifier] pre_save_validate rate limited — waiting 60s and retrying...")
                time.sleep(60)
                continue
            log.warning(f"[verifier] pre_save_validate failed: {e} — saving anyway")
            break

    return result

VerifierAgent.pre_save_validate = _verifier_pre_save_validate
