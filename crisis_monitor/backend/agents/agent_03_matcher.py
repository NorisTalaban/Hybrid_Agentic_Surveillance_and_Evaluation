"""
agents/agent_03_matcher.py — Agent 03: MATCHER
Links classified_events to existing crises or creates new ones.
- Single batch call for all events
- Explicit independence check (country overlap alone is not enough)
- Severity = median of last 48h events

FIXES:
  - FIX-04: removed monkey-patching of pre_save_validate and run()
            both are now clean overrides in the class
  - FIX-11: BATCH_SIZE moved to __init__ as self.batch_size
  - removed the duplicate run() that was present in the original file
"""

import uuid
import json
import statistics
from datetime import datetime, timezone, timedelta
from agents.base_agent import BaseAgent
from config import MODEL_SONNET, CRISIS_STATUSES, normalize_status
from utils import get_client, get_lat_lng, get_logger, track

log = get_logger("matcher")

SYSTEM_PROMPT = """You are a crisis matching specialist.
You receive:
  1. A list of NEW classified events (from recent news)
  2. A list of ACTIVE crises already in the database

Your job: for each new event, decide:
  A) EXISTING — this event belongs to an existing crisis
  B) NEW — this is a genuinely new, independent crisis
  C) DUPLICATE — this looks like a crisis already in DB (flag, don't create)

CRITICAL RULE:
  Country overlap alone is NOT enough to match an event to a crisis.
  Ask: "Is this event PART OF the same crisis, or a separate independent event?"
  Example: earthquake in Iran ≠ Iran nuclear crisis.

Severity recalculation:
  When updating an existing crisis, include new_severity = median of recent events.

CRITICAL: new_status MUST be one of: active, escalating, de_escalating, stable, resolved.
Do NOT invent other status values like 'potentially_de_escalating' or 'worsening'.

Return ONLY a JSON object:
{
  "decisions": [
    {
      "event_id": "uuid",
      "match": "existing|new|duplicate",
      "crisis_id": "uuid or null",
      "is_independent": true/false,
      "independence_reasoning": "Why independent or not",
      "crisis_update": {
        "new_severity": 8,
        "new_status": "escalating",
        "update_reason": "Major escalation: airstrike on capital"
      },
      "possible_duplicate_of": "Crisis name or null",
      "new_crisis": {
        "name": "...",
        "type": "conflict",
        "severity": 7,
        "primary_countries": ["PK"],
        "summary": "...",
        "source": "enricher"
      }
    }
  ]
}

Return ONLY valid JSON. No preamble.

CRITICAL: Your entire response must be a single JSON object starting with { and ending with }.
Do NOT include any markdown, headers, explanations, or text outside the JSON.
Do NOT use ```json fences. Return raw JSON only."""

MATCHER_VALIDATOR_SYSTEM = """You are a crisis deduplication and matching auditor.

You receive matcher decisions for a batch of events, plus the current list of active crises.

For EACH decision audit:
  1. NEW decisions: is this truly a new independent crisis, or should it match an existing one?
     Check for: same country + same type + similar timeframe = likely duplicate.
  2. EXISTING decisions: does the matched crisis make logical sense?
     Country overlap alone is NOT enough — the event must be PART OF that crisis.
  3. DUPLICATE flags: confirm or deny.

For new crises, also verify: is the name specific enough? Is severity realistic?

Return ONLY a JSON object with corrected decisions:
{
  "decisions": [
    {
      "event_id": "...",
      "match": "existing|new|duplicate",
      "crisis_id": "uuid or null",
      "is_independent": true/false,
      "independence_reasoning": "...",
      "crisis_update": { ... },
      "possible_duplicate_of": "name or null",
      "new_crisis": { ... },
      "_validation_note": "changed from new to existing: same Sudan conflict"
    }
  ]
}

Be conservative: prefer matching to existing over creating new crises.
Return ONLY valid JSON. No preamble."""


class MatcherAgent(BaseAgent):

    def __init__(self):
        super().__init__(model=MODEL_SONNET, agent_name="matcher")
        self.db         = get_client()
        self.events     = []
        self.crises     = []
        self.batch_size = 10  # FIX-11: was class attribute, now in __init__

    def check_data(self) -> bool:
        result = (self.db.table("classified_events")
                  .select("*")
                  .is_("crisis_id", "null")
                  .execute())
        self.events = result.data or []

        result2 = (self.db.table("crises")
                   .select("id, name, type, status, severity, countries, primary_country, summary")
                   .neq("status", "resolved")
                   .execute())
        self.crises = result2.data or []

        return len(self.events) > 0

    def build_prompt(self, events_batch: list = None) -> list[dict]:
        events_to_use = events_batch or self.events
        events_compact = [
            {
                "event_id":    e["id"],
                "title":       e["title_clean"],
                "summary":     e["summary"],
                "type":        e["event_type"],
                "severity":    e["severity"],
                "countries":   [c["code"] for c in (e.get("countries_inv") or [])],
                "primary":     e.get("primary_country"),
                "published_at": e.get("published_at"),
            }
            for e in events_to_use
        ]
        crises_compact = [
            {
                "crisis_id": c["id"],
                "name":      c["name"],
                "type":      c["type"],
                "status":    c["status"],
                "severity":  c["severity"],
                "countries": c.get("countries", []),
                "summary":   (c.get("summary") or "")[:200],
            }
            for c in self.crises
        ]

        content = (
            f"NEW EVENTS ({len(events_compact)}):\n"
            f"{json.dumps(events_compact, ensure_ascii=False, indent=2)}\n\n"
            f"ACTIVE CRISES ({len(crises_compact)}):\n"
            f"{json.dumps(crises_compact, ensure_ascii=False, indent=2)}"
        )
        return [{"role": "user", "content": content}]

    def validate_output(self, raw: str) -> dict:
        import re
        json_matches = re.findall(r'\{[\s\S]*\}', raw, re.DOTALL)
        data = None
        for candidate in reversed(json_matches):
            try:
                parsed = json.loads(candidate)
                if isinstance(parsed, dict) and "decisions" in parsed:
                    data = parsed
                    break
            except json.JSONDecodeError:
                continue

        if data is None:
            data = self.parse_json(raw)

        if "decisions" not in data:
            raise ValueError("Matcher output missing 'decisions' key")
        return data

    def pre_save_validate(self, output: dict) -> dict:
        """FIX-04: Sonnet audit is now a clean override, not a monkey-patch."""
        decisions = output.get("decisions", [])
        if not decisions:
            return output

        crises_compact = [
            {
                "crisis_id": c["id"],
                "name":      c["name"],
                "type":      c["type"],
                "countries": c.get("countries", []),
                "status":    c["status"],
            }
            for c in self.crises
        ]

        try:
            response = self.client.messages.create(
                model=MODEL_SONNET,
                max_tokens=2000,
                system=MATCHER_VALIDATOR_SYSTEM,
                messages=[{
                    "role": "user",
                    "content": (
                        f"Audit these {len(decisions)} matcher decisions.\n\n"
                        f"DECISIONS:\n{json.dumps(decisions, ensure_ascii=False, indent=2)}\n\n"
                        f"ACTIVE CRISES ({len(crises_compact)}):\n"
                        f"{json.dumps(crises_compact, ensure_ascii=False, indent=2)}"
                    )
                }],
            )
            track(MODEL_SONNET, response.usage.input_tokens,
                  response.usage.output_tokens, label="matcher_validator")

            raw = next((b.text for b in response.content if b.type == "text"), "")
            audited = self.parse_json(raw)
            if isinstance(audited, dict) and "decisions" in audited:
                for corr in audited["decisions"]:
                    note = corr.pop("_validation_note", "")
                    if note:
                        log.info(f"[matcher] Correction: {note}")
                return audited
        except Exception as e:
            log.warning(f"[matcher] pre_save_validate failed: {e} — using original output")

        return output

    def save(self, output: dict) -> None:
        now       = datetime.now(timezone.utc).isoformat()
        decisions = output.get("decisions", [])
        created_this_run = {}

        for decision in decisions:
            match    = decision.get("match")
            event_id = decision.get("event_id")

            if match == "existing":
                self._handle_existing(decision, event_id, now)

            elif match == "new":
                if decision.get("possible_duplicate_of"):
                    log.warning(f"Possible dup flagged: {decision.get('possible_duplicate_of')}")
                    self._flag_duplicate(event_id, decision["possible_duplicate_of"])
                    continue
                crisis_id = self._create_new_crisis(decision, event_id, now, created_this_run)
                if crisis_id and decision.get("new_crisis", {}).get("name"):
                    created_this_run[decision["new_crisis"]["name"]] = crisis_id

            elif match == "duplicate":
                self._flag_duplicate(event_id, decision.get("possible_duplicate_of", "unknown"))

    def run(self) -> bool:
        """FIX-04: single run() in the class — removed duplicate + original monkey-patches."""
        self.log.info(f"[{self.name}] Starting...")

        if not self.check_data():
            self.log.info(f"[{self.name}] No data to process. Skipping.")
            return False

        all_events = self.events[:]
        total      = len(all_events)
        processed  = 0

        self.log.info(f"[{self.name}] Processing {total} events in batches of {self.batch_size}...")

        while processed < total:
            batch = all_events[processed:processed + self.batch_size]
            self.log.info(
                f"[{self.name}] Batch {processed // self.batch_size + 1}: "
                f"{len(batch)} events ({processed + 1}-{processed + len(batch)} of {total})"
            )
            messages = self.build_prompt(events_batch=batch)
            for attempt in range(2):
                try:
                    raw       = self.call_llm(messages, system=SYSTEM_PROMPT)
                    validated = self.validate_output(raw)
                    # FIX-03: pre_save_validate is now actually called
                    validated = self.pre_save_validate(validated)
                    self.save(validated)
                    break
                except (ValueError, json.JSONDecodeError) as e:
                    if attempt == 0:
                        self.log.warning(f"[{self.name}] Batch parse failed, retrying: {e}")
                    else:
                        self.log.error(f"[{self.name}] Batch failed after retry: {e}")
            processed += len(batch)

        self.log.info(f"[{self.name}] Done. Processed {total} events.")
        return True

    # ── Internal helpers ──────────────────────────────────────────────────

    def _handle_existing(self, decision: dict, event_id: str, now: str):
        crisis_id = decision.get("crisis_id")
        if not crisis_id:
            return

        # FIX: verify crisis_id exists in DB before inserting FK references
        if not self._crisis_exists(crisis_id):
            log.warning(f"[matcher] crisis_id {crisis_id} not found in DB — LLM hallucinated UUID. Skipping.")
            return

        self._write_crisis_event(crisis_id, event_id, decision, now)

        update = decision.get("crisis_update") or {}
        if update:
            new_sev = update.get("new_severity") or self._compute_median_severity(crisis_id)
            # Clamp severity to DB constraint range 1-10
            if new_sev is not None:
                new_sev = max(1, min(10, int(new_sev))) if isinstance(new_sev, (int, float)) else None
            patch = {
                "last_event_at": now,
                "last_updated":  now,
                "event_count":   self._increment_event_count(crisis_id),
            }
            if new_sev:
                patch["severity"] = new_sev
                try:
                    current = self.db.table("crises").select("severity_peak").eq("id", crisis_id).single().execute()
                    current_peak = (current.data or {}).get("severity_peak", 0)
                    if new_sev > current_peak:
                        patch["severity_peak"] = new_sev
                except Exception:
                    patch["severity_peak"] = new_sev
            if update.get("new_status"):
                patch["status"] = normalize_status(update["new_status"])  # FIX M-02
            if update.get("update_reason"):
                patch["summary"] = update["update_reason"][:500]

            # FIX R-03: safe country merge — only add countries with relevant roles, cap at 20
            self._safe_merge_countries(crisis_id, event_id, patch)

            try:
                self.db.table("crises").update(patch).eq("id", crisis_id).execute()
            except Exception as e:
                log.error(f"Failed to update crisis {crisis_id}: {e}")

        try:
            self.db.table("classified_events").update({
                "crisis_id": crisis_id
            }).eq("id", event_id).execute()
        except Exception as e:
            log.error(f"Failed to link event {event_id} to crisis {crisis_id}: {e}")

    def _safe_merge_countries(self, crisis_id: str, event_id: str, patch: dict):
        """FIX R-03: Merge event countries into crisis only if roles are relevant. Cap at 20."""
        RELEVANT_ROLES = {"affected", "aggressor", "target", "perpetrator", "involved", "primary"}
        MAX_COUNTRIES = 20
        try:
            event = next((e for e in self.events if e["id"] == event_id), None)
            if not event:
                return
            crisis_res = self.db.table("crises").select("countries").eq("id", crisis_id).single().execute()
            current = list((crisis_res.data or {}).get("countries") or [])
            if len(current) >= MAX_COUNTRIES:
                return  # already at cap — likely over-matching
            new_codes = []
            for c in (event.get("countries_inv") or []):
                code = c.get("code") if isinstance(c, dict) else c
                role = (c.get("role", "") if isinstance(c, dict) else "").lower()
                if code and code not in current and role in RELEVANT_ROLES:
                    new_codes.append(code)
            if new_codes:
                merged = current + new_codes[:MAX_COUNTRIES - len(current)]
                patch["countries"] = merged
                log.debug(f"Merged countries for crisis {crisis_id}: +{new_codes}")
        except Exception as e:
            log.debug(f"Country merge skipped for {crisis_id}: {e}")

    def _create_new_crisis(self, decision: dict, event_id: str, now: str,
                           created_this_run: dict) -> str | None:
        nc = decision.get("new_crisis")
        if not nc or not nc.get("name"):
            return None

        name = nc["name"]
        if name in created_this_run:
            log.info(f"Dedup: '{name}' already created this run, linking event")
            self._link_event(event_id, created_this_run[name], now)
            return created_this_run[name]

        countries = nc.get("primary_countries", [])
        primary   = countries[0] if countries else None
        lat = lng = None
        if primary:
            coords = get_lat_lng(primary)
            if coords:
                lat, lng = coords

        crisis_id = str(uuid.uuid4())
        # FIX D: validate source against DB constraint (scanner|enricher|manual)
        source = nc.get("source", "enricher")
        if source not in ("scanner", "enricher", "manual"):
            source = "enricher"
        # Validate severity (DB constraint: 1-10)
        raw_sev = nc.get("severity", 5)
        sev = max(1, min(10, int(raw_sev))) if isinstance(raw_sev, (int, float)) else 5
        # Validate type (DB constraint)
        crisis_type = nc.get("type", "conflict")
        if crisis_type not in ("conflict", "disaster", "economic", "political", "health"):
            crisis_type = "conflict"
        try:
            self.db.table("crises").insert({
                "id":              crisis_id,
                "name":            name,
                "type":            crisis_type,
                "status":          "active",
                "severity":        sev,
                "severity_peak":   sev,
                "countries":       countries,
                "primary_country": primary,
                "lat":             lat,
                "lng":             lng,
                "event_count":     1,
                "source":          source,
                "summary":         nc.get("summary", ""),
                "first_event_at":  now,
                "last_event_at":   now,
                "last_updated":    now,
                "media_gap":       False,
            }).execute()
            log.info(f"Created new crisis: {name} (id={crisis_id})")
        except Exception as e:
            log.error(f"Failed to create crisis '{name}': {e}")
            return None

        self._write_crisis_event(crisis_id, event_id, decision, now)
        self._link_event(event_id, crisis_id, now)
        return crisis_id

    def _write_crisis_event(self, crisis_id: str, event_id: str, decision: dict, now: str):
        update   = decision.get("crisis_update") or {}
        event    = next((e for e in self.events if e["id"] == event_id), {})
        severity = update.get("new_severity") or event.get("severity", 5)
        # Clamp severity to DB constraint range 1-10
        if isinstance(severity, (int, float)):
            severity = max(1, min(10, int(severity)))
        else:
            severity = 5
        status   = normalize_status(update.get("new_status") or "active")  # FIX M-02

        # FIX E: verify event_id exists in classified_events before FK insert
        if event_id:
            try:
                check = self.db.table("classified_events").select("id").eq("id", event_id).execute()
                if not check.data:
                    log.warning(f"[matcher] event_id {event_id} not in classified_events — skipping crisis_event insert")
                    return
            except Exception:
                pass  # proceed anyway if check fails

        try:
            self.db.table("crisis_events").insert({
                "id":            str(uuid.uuid4()),
                "crisis_id":     crisis_id,
                "event_id":      event_id,
                "event_date":    event.get("published_at") or now,
                "severity_at":   severity,
                "status_at":     status,
                "is_escalation": status == "escalating",
                "source":        "matcher",    # DB constraint accepts 'matcher'
                "created_at":    now,
            }).execute()
        except Exception as e:
            log.error(f"Failed to insert crisis_event: {e}")

    def _link_event(self, event_id: str, crisis_id: str, now: str):
        try:
            self.db.table("classified_events").update({
                "crisis_id": crisis_id
            }).eq("id", event_id).execute()
        except Exception as e:
            log.error(f"Failed to link event {event_id}: {e}")

    def _flag_duplicate(self, event_id: str, possible_dup_of: str):
        try:
            self.db.table("classified_events").update({
                "crisis_id": None,
                "sub_type":  f"DUPLICATE_OF:{possible_dup_of}"
            }).eq("id", event_id).execute()
        except Exception as e:
            log.error(f"Failed to flag duplicate for event {event_id}: {e}")

    def _crisis_exists(self, crisis_id: str) -> bool:
        """FIX: Check if a crisis_id actually exists in DB before FK insert."""
        try:
            result = self.db.table("crises").select("id").eq("id", crisis_id).execute()
            return bool(result.data)
        except Exception:
            return False

    def _increment_event_count(self, crisis_id: str) -> int:
        try:
            result = self.db.table("crises").select("event_count").eq("id", crisis_id).single().execute()
            return (result.data.get("event_count") or 0) + 1
        except Exception:
            return 1

    def _compute_median_severity(self, crisis_id: str) -> int | None:
        try:
            since  = (datetime.now(timezone.utc) - timedelta(hours=48)).isoformat()
            result = (self.db.table("crisis_events")
                      .select("severity_at")
                      .eq("crisis_id", crisis_id)
                      .gte("event_date", since)
                      .execute())
            sevs = [r["severity_at"] for r in (result.data or []) if r.get("severity_at")]
            if sevs:
                return int(statistics.median(sevs))
        except Exception:
            pass
        return None
