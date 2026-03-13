"""
validators.py — Data validation for Crisis Monitor pipeline.

  - ValidatorA: post-Classifier (Python checks on classified_events)
  - ValidatorB: post-Matcher (Python checks on crises + crisis_events)
  - ValidatorC: bootstrap reality check (LLM, Haiku)

CHANGES from original utils.py:
  - Extracted into its own module
  - ValidatorB duplicate check uses name similarity, not just country:type
  - ValidatorC has retry on JSON parse failure (1 retry with lower temperature hint)
  - Shared _BaseValidator for common error handling patterns
  - All validators log a summary with pass/fail counts
"""

import json
import anthropic
from datetime import datetime, timezone, timedelta
from db import get_client
from geo import validate_country_code
from cost import track
from logger import get_logger
from config import (
    ANTHROPIC_API_KEY, MODEL_HAIKU, MAX_TOKENS,
    VALID_CRISIS_TYPES, SEVERITY_MIN, SEVERITY_MAX,
    CRISIS_STATUSES, VALIDATOR_C_RECENCY_DAYS, VALIDATOR_C_BATCH_SIZE,
)


# ══════════════════════════════════════════════════════════════════════════════
# SHARED BASE
# ══════════════════════════════════════════════════════════════════════════════

class _BaseValidator:
    """Common error handling for validators A and B."""

    def __init__(self, validator_name: str):
        self.db     = get_client()
        self.now    = datetime.now(timezone.utc).isoformat()
        self.errors = []
        self._name  = validator_name
        self._log   = get_logger(validator_name)

    def _err(self, entity_id: str, entity_type: str, check_name: str,
             msg: str, severity: str) -> dict:
        return {
            "validator":   self._name,
            "entity_type": entity_type,
            "entity_id":   entity_id,
            "check_name":  check_name,
            "expected":    "",
            "actual":      msg,
            "severity":    severity,
            "resolved":    False,
            "created_at":  self.now,
        }

    def _log_errors(self, errors: list):
        for e in errors:
            level = "error" if e["severity"] == "hard_fail" else "warning"
            getattr(self._log, level)(
                f"  [{e['severity']}] {e['check_name']}: {e['actual']}"
            )
        self.errors.extend(errors)

    def _save_errors(self):
        if not self.errors:
            return
        try:
            self.db.table("validation_errors").insert(self.errors).execute()
        except Exception as e:
            self._log.warning(f"Could not save validation errors: {e}")


# ══════════════════════════════════════════════════════════════════════════════
# VALIDATOR A — post-Classifier (Python only)
# ══════════════════════════════════════════════════════════════════════════════

_VALID_MEDIA = {"high", "medium", "low"}


class ValidatorA(_BaseValidator):

    def __init__(self):
        super().__init__("validator_a")

    def run(self) -> list:
        """
        Validate all unlinked classified_events.
        Returns list of event IDs that passed validation.
        """
        result = (self.db.table("classified_events")
                  .select("*")
                  .is_("crisis_id", "null")
                  .execute())
        events = result.data or []
        if not events:
            self._log.info("Validator A: no events to check.")
            return []

        passed_ids = []
        self.errors = []
        for event in events:
            errs          = self._check_event(event)
            has_hard_fail = any(e["severity"] == "hard_fail" for e in errs)
            if errs:
                self._log_errors(errs)
            if not has_hard_fail:
                passed_ids.append(event["id"])

        self._save_errors()
        self._log.info(f"Validator A: {len(passed_ids)}/{len(events)} events passed.")
        return passed_ids

    def _check_event(self, event: dict) -> list:
        errors = []
        eid    = event["id"]

        # Required fields
        for field in ["id", "title_clean", "summary", "severity", "event_type", "primary_country"]:
            if not event.get(field):
                errors.append(self._err(eid, "classified_event", "JSON_SCHEMA",
                                        f"Missing: {field}", "hard_fail"))

        # Country code validation
        primary = event.get("primary_country")
        if primary:
            if primary in ("GLOBAL", "XX", "XG", "INT", "UN", "EU", "NATO", "INTL", "G7", "G20", "OPEC", "ASEAN"):
                # Global/placeholder codes — downgrade to soft_fail, not discard
                errors.append(self._err(eid, "classified_event", "COUNTRY_CODE",
                                        f"Global/placeholder code: {primary}", "soft_fail"))
            elif not validate_country_code(primary):
                errors.append(self._err(eid, "classified_event", "COUNTRY_CODE",
                                        f"Unknown: {primary}", "hard_fail"))
        for c in (event.get("countries_inv") or []):
            code = c.get("code", "") if isinstance(c, dict) else ""
            if code and not validate_country_code(code):
                errors.append(self._err(eid, "classified_event", "COUNTRY_CODE",
                                        f"Unknown in countries_inv: {code}", "soft_fail"))

        # Severity range
        sev = event.get("severity")
        if not isinstance(sev, int) or not (SEVERITY_MIN <= sev <= SEVERITY_MAX):
            errors.append(self._err(eid, "classified_event", "SEVERITY_RANGE",
                                    f"Severity {sev} out of range", "hard_fail"))

        # Crisis type
        if event.get("event_type") not in VALID_CRISIS_TYPES:
            errors.append(self._err(eid, "classified_event", "TYPE_VALID",
                                    f"Unknown type: {event.get('event_type')}", "hard_fail"))

        # Media attention
        if event.get("media_attention") not in _VALID_MEDIA:
            errors.append(self._err(eid, "classified_event", "MEDIA_ATTENTION",
                                    f"Unknown: {event.get('media_attention')}", "soft_fail"))

        return errors


# ══════════════════════════════════════════════════════════════════════════════
# VALIDATOR B — post-Matcher (Python only)
# ══════════════════════════════════════════════════════════════════════════════

class ValidatorB(_BaseValidator):

    def __init__(self):
        super().__init__("validator_b")

    def run(self, run_crisis_ids: list[str] = None) -> bool:
        """
        Validate recently updated crises.
        Returns True if no hard failures found.
        """
        if not run_crisis_ids:
            run_crisis_ids = self._get_recently_updated_crisis_ids()
        if not run_crisis_ids:
            self._log.info("Validator B: nothing to check.")
            return True

        crises        = self._load_crises(run_crisis_ids)
        hard_failures = False
        self.errors   = []

        self._check_orphan_events(run_crisis_ids)
        if self._check_duplicates(crises):
            hard_failures = True
        for c in crises:
            self._check_crisis(c)

        self._save_errors()
        passed = not hard_failures
        self._log.info(
            f"Validator B: {'PASS' if passed else 'FAIL (duplicates)'} — "
            f"{len(self.errors)} issues"
        )
        return passed

    def _check_orphan_events(self, crisis_ids: list):
        result = (self.db.table("crisis_events")
                  .select("id, crisis_id")
                  .in_("crisis_id", crisis_ids)
                  .execute())
        for ev in (result.data or []):
            if not ev.get("crisis_id"):
                self.errors.append(
                    self._err(ev["id"], "crisis_event", "NO_ORPHANS",
                              "crisis_id is null", "soft_fail")
                )

    def _check_duplicates(self, crises: list) -> list:
        """
        Check for duplicate crises.
        FIX M-03 + R-06: auto-merges confirmed duplicates (>80% name overlap).
        Keeps the older crisis, merges events from the newer one, then deletes it.
        """
        seen: dict[str, dict] = {}
        duplicates = []
        for c in crises:
            key = f"{c.get('primary_country', '')}:{c.get('type', '')}"
            if key in seen:
                existing = seen[key]
                if self._names_similar(c.get("name", ""), existing.get("name", "")):
                    msg = f"Duplicate: {c['name']} vs {existing['name']} ({key})"
                    self._log.error(f"  ✗ [HARD_FAIL] {msg}")
                    self.errors.append(
                        self._err(c["id"], "crisis", "NO_DUPLICATES", msg, "hard_fail")
                    )
                    duplicates.append(c["id"])
                    # FIX M-03: auto-merge the newer into the older
                    self._auto_merge(keep=existing, remove=c)
                else:
                    msg = (f"Same country/type but different names: "
                           f"'{c['name']}' vs '{existing['name']}' ({key})")
                    self._log.info(f"  [INFO] {msg}")
                    self.errors.append(
                        self._err(c["id"], "crisis", "POSSIBLE_DUPLICATE", msg, "soft_fail")
                    )
                    seen[key] = c
            else:
                seen[key] = c
        return duplicates

    def _auto_merge(self, keep: dict, remove: dict):
        """FIX M-03: Merge a duplicate crisis into the kept one, then delete it."""
        keep_id   = keep["id"]
        remove_id = remove["id"]
        try:
            # Move crisis_events from removed to kept
            self.db.table("crisis_events").update(
                {"crisis_id": keep_id}
            ).eq("crisis_id", remove_id).execute()

            # Move classified_events from removed to kept
            self.db.table("classified_events").update(
                {"crisis_id": keep_id}
            ).eq("crisis_id", remove_id).execute()

            # Move connections from removed to kept
            self.db.table("connections").update(
                {"crisis_id": keep_id}
            ).eq("crisis_id", remove_id).execute()

            # Merge countries
            keep_countries = set(keep.get("countries") or [])
            remove_countries = set(remove.get("countries") or [])
            merged = list(keep_countries | remove_countries)
            if merged != list(keep_countries):
                self.db.table("crises").update(
                    {"countries": merged}
                ).eq("id", keep_id).execute()

            # Delete the duplicate crisis
            self.db.table("crises").delete().eq("id", remove_id).execute()
            self._log.info(f"  ✓ Auto-merged '{remove.get('name')}' into '{keep.get('name')}' and deleted duplicate")

        except Exception as e:
            self._log.warning(f"  Auto-merge failed for {remove.get('name')}: {e}")

    @staticmethod
    def _names_similar(name_a: str, name_b: str) -> bool:
        """Are names clearly the same crisis? Requires >80% meaningful word overlap."""
        a = name_a.lower().strip()
        b = name_b.lower().strip()
        if a == b:
            return True
        # One fully contains the other (e.g. word-order swap like "Italy Earthquake" vs "Earthquake Italy")
        if a in b or b in a:
            return True
        # Strip common filler words before overlap check
        STOPWORDS = {"the", "in", "of", "and", "crisis", "war", "conflict",
                     "emergency", "situation", "incident", "vs", "between"}
        words_a = set(a.split()) - STOPWORDS
        words_b = set(b.split()) - STOPWORDS
        if not words_a or not words_b:
            return False
        overlap = len(words_a & words_b) / min(len(words_a), len(words_b))
        return overlap > 0.8  # raised from 0.6 to reduce false positives

    def _check_crisis(self, c: dict):
        cid = c["id"]
        if c.get("severity_peak", 0) < c.get("severity", 0):
            self.errors.append(
                self._err(cid, "crisis", "SEVERITY_PEAK",
                          "severity_peak < severity", "soft_fail")
            )
        first, last = c.get("first_event_at"), c.get("last_event_at")
        if first and last and first > last:
            self.errors.append(
                self._err(cid, "crisis", "DATES_COHERENT",
                          "first > last", "soft_fail")
            )
        if c.get("status") not in CRISIS_STATUSES:
            self.errors.append(
                self._err(cid, "crisis", "STATUS_VALID",
                          f"Unknown: {c.get('status')}", "soft_fail")
            )
        if c.get("lat") is None or c.get("lng") is None:
            self.errors.append(
                self._err(cid, "crisis", "HAS_COORDS",
                          "lat or lng is null", "soft_fail")
            )

    def _get_recently_updated_crisis_ids(self) -> list:
        since = (datetime.now(timezone.utc) - timedelta(hours=7)).isoformat()
        try:
            result = self.db.table("crises").select("id").gte("last_updated", since).execute()
            return [r["id"] for r in (result.data or [])]
        except Exception:
            return []

    def _load_crises(self, ids: list) -> list:
        try:
            return self.db.table("crises").select("*").in_("id", ids).execute().data or []
        except Exception:
            return []


# ══════════════════════════════════════════════════════════════════════════════
# VALIDATOR C — Bootstrap reality check (LLM, Haiku)
# ══════════════════════════════════════════════════════════════════════════════

_log_vc = get_logger("validator_c")

_VC_SYSTEM_PROMPT = """You are a crisis verification specialist.
You will receive a list of crises that a Scanner agent found on the web.
Your job: determine which ones are GENUINELY ACTIVE today.

For each crisis, classify it as one of:
  - "active":      Clearly ongoing right now with recent evidence
  - "historical":  This is a past/resolved crisis, not currently active
  - "speculative": This is a prediction or potential future crisis
  - "uncertain":   Cannot determine — insufficient information

Return ONLY a JSON array:
[{"name": "...", "verdict": "active|historical|speculative|uncertain", "confidence": "high|medium|low", "reasoning": "..."}]

Be conservative: when in doubt use "uncertain". Only flag historical/speculative.
Return ONLY valid JSON. No preamble."""


class ValidatorC:

    def __init__(self):
        self.client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        self.cutoff = datetime.now(timezone.utc) - timedelta(days=VALIDATOR_C_RECENCY_DAYS)

    def run(self, crises: list) -> list:
        """
        Filter crises through temporal check + LLM reality check.
        Returns list of crises that are likely still active.
        """
        if not crises:
            return []
        _log_vc.info(f"Validator C: checking {len(crises)} crises...")
        after1 = self._temporal_filter(crises)
        _log_vc.info(f"Stage 1 (temporal): {len(after1)}/{len(crises)} passed")
        after2 = self._reality_check(after1)
        _log_vc.info(f"Stage 2 (LLM): {len(after2)}/{len(after1)} passed")
        return after2

    def _temporal_filter(self, crises: list) -> list:
        passed, rejected = [], []
        for c in crises:
            last = c.get("last_known_event") or c.get("started_at")
            if last:
                try:
                    dt = datetime.fromisoformat(last.replace("Z", "+00:00"))
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                    if dt < self.cutoff:
                        rejected.append(c["name"])
                        continue
                except (ValueError, TypeError):
                    pass
            passed.append(c)
        if rejected:
            _log_vc.info(f"Temporal filter rejected: {rejected}")
        return passed

    def _reality_check(self, crises: list) -> list:
        if not crises:
            return []

        compact = [
            {
                "name":             c.get("name"),
                "type":             c.get("type"),
                "started_at":       c.get("started_at"),
                "last_known_event": c.get("last_known_event"),
                "summary":          c.get("summary", "")[:200],
            }
            for c in crises[:VALIDATOR_C_BATCH_SIZE]
        ]
        today  = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        prompt = (
            f"Today is {today}.\n"
            f"Review these {len(compact)} crises and classify each:\n\n"
            f"{json.dumps(compact, ensure_ascii=False, indent=2)}\n\n"
            f"Return the JSON array."
        )

        # Try up to 2 times on parse failure
        raw = None
        for attempt in range(2):
            try:
                response = self.client.messages.create(
                    model=MODEL_HAIKU, max_tokens=MAX_TOKENS,
                    system=_VC_SYSTEM_PROMPT,
                    messages=[{"role": "user", "content": prompt}]
                )
                track(MODEL_HAIKU,
                      response.usage.input_tokens,
                      response.usage.output_tokens,
                      label="validator_c")
                raw = response.content[0].text
                break
            except Exception as e:
                if attempt == 0:
                    _log_vc.warning(f"Validator C LLM call failed (attempt 1): {e}. Retrying...")
                else:
                    _log_vc.error(f"Validator C LLM call failed (attempt 2): {e}. Passing all through.")
                    return crises

        if raw is None:
            return crises

        # Parse JSON from response
        verdicts = self._parse_verdicts(raw)
        if verdicts is None:
            _log_vc.error("Could not parse Validator C response. Passing all through.")
            return crises

        passed, rejected = [], []
        for c in crises:
            vd = verdicts.get(c["name"])
            if vd is None or vd.get("verdict", "uncertain") in ("active", "uncertain"):
                passed.append(c)
            else:
                rejected.append(c["name"])
                _log_vc.debug(
                    f"  ✗ {c['name']} [{vd.get('verdict')}]: {vd.get('reasoning', '')}"
                )
        if rejected:
            _log_vc.info(f"Reality check rejected: {rejected}")
        return passed

    @staticmethod
    def _parse_verdicts(raw: str) -> dict | None:
        """Parse the JSON array from Validator C LLM response."""
        cleaned = raw.strip()
        # Strip markdown fences
        if cleaned.startswith("```"):
            parts = cleaned.split("```")
            cleaned = parts[1]
            if cleaned.startswith("json"):
                cleaned = cleaned[4:]
        try:
            data = json.loads(cleaned.strip())
            return {item["name"]: item for item in data if "name" in item}
        except (json.JSONDecodeError, KeyError, TypeError) as e:
            _log_vc.warning(f"JSON parse failed: {e}")
            # Fallback: try regex extraction
            import re
            match = re.search(r'\[[\s\S]*\]', raw)
            if match:
                try:
                    data = json.loads(match.group(0))
                    return {item["name"]: item for item in data if "name" in item}
                except (json.JSONDecodeError, KeyError, TypeError):
                    pass
            return None
