"""
agents/agent_02_classifier.py — Agent 02: CLASSIFIER
Classifies raw_articles into structured classified_events.
Processes in batches of 15 articles per call.

FIX: uses MODEL_HAIKU instead of MODEL_SONNET (structured/mechanical task)
     Savings: ~$11/month
"""

import uuid
import json
from datetime import datetime, timezone
from agents.base_agent import BaseAgent
from config import MODEL_HAIKU, VALID_CRISIS_TYPES   # ← MODEL_HAIKU
from utils import get_client
from utils import get_logger

log = get_logger("classifier")

SYSTEM_PROMPT = """You are a crisis classification expert.
You receive a batch of news articles. For each one, determine:
  1. Is this about an active crisis? (is_crisis: true/false)
  2. If yes, classify it with the structured schema below.

Crisis types: conflict | disaster | economic | political | health

Severity scale (1-10):
  1-2: Minor/local   3-4: Notable/regional   5-6: Significant/multi-country
  7-8: Severe/large-scale   9-10: Catastrophic

IMPORTANT — geolocation:
  - countries_involved = who is PART OF the crisis (for map markers)
  - event_location = where it PHYSICALLY happened (for geocoding only)
  - Map markers go on countries_involved, NOT event_location

Return a JSON array, one object per article:
[
  {
    "article_id": "...",
    "is_crisis": true,
    "title_clean": "Short factual title",
    "summary": "1-2 sentence summary",
    "severity": 6,
    "severity_reasoning": "Why this severity",
    "type": "conflict",
    "sub_type": "airstrike",
    "countries_involved": [
      {"name": "Iran", "code": "IR", "role": "aggressor"},
      {"name": "Iraq", "code": "IQ", "role": "affected"}
    ],
    "event_location": {"name": "Baghdad", "type": "city", "country_code": "IQ"},
    "primary_country": "IQ",
    "media_attention": "high",
    "real_impact": "high",
    "keywords": ["airstrike", "military", "civilian casualties"]
  }
]

If is_crisis=false, you may omit all other fields.
Return ONLY valid JSON. No preamble.

CRITICAL FORMATTING RULES:
1. Your entire response must be a single JSON array: starts with [ ends with ]
2. Do NOT use markdown fences (no ```json, no ```)
3. Do NOT write anything before the [ or after the ]
4. Every string must use double quotes ("), never single quotes
5. Every object must be properly closed with }
6. The array must be properly closed with ]
7. If unsure about an article, set is_crisis=false — never omit an article
8. Return exactly one object per article

Correct output example (condensed):
[{"article_id":"id1","is_crisis":false},{"article_id":"id2","is_crisis":true,"title_clean":"Title","summary":"Brief.","severity":5,"severity_reasoning":"reason","type":"conflict","sub_type":"skirmish","countries_involved":[{"name":"Iran","code":"IR","role":"aggressor"}],"event_location":{"name":"Tehran","type":"city","country_code":"IR"},"primary_country":"IR","media_attention":"medium","real_impact":"medium","keywords":["keyword"]}]"""

CLASSIFIER_VALIDATOR_SYSTEM = """You are a crisis classification auditor. You receive classified events and correct mistakes.

For each event check: severity justified? primary_country correct? type correct?
Only output events you CHANGED. Unchanged events should be omitted.

Return a JSON object (NOT array):
{
  "corrections": [
    {"article_id": "...", "field": "severity", "old": 3, "new": 7, "reason": "mass casualties"},
    {"article_id": "...", "field": "primary_country", "old": "US", "new": "IQ", "reason": "event in Iraq"},
    {"article_id": "...", "field": "type", "old": "political", "new": "conflict", "reason": "armed clash"}
  ],
  "removals": ["article_id_1"]
}

If everything is correct: {"corrections": [], "removals": []}
Return ONLY valid JSON. No preamble. No markdown."""


class ClassifierAgent(BaseAgent):

    def __init__(self):
        super().__init__(model=MODEL_HAIKU, agent_name="classifier")  # ← HAIKU
        self.db       = get_client()
        self.articles = []

    def check_data(self) -> bool:
        result = (self.db.table("raw_articles")
                  .select("id, title, description, content, url, published_at, source_name")
                  .eq("status", "new")
                  .order("published_at", desc=False)
                  .execute())
        self.articles = result.data or []
        return len(self.articles) > 0

    def build_prompt(self) -> list[dict]:
        batch = self.articles[:15]
        articles_json = json.dumps([
            {
                "article_id":  a["id"],
                "title":       a.get("title", ""),
                "description": a.get("description", ""),
                "content":     (a.get("content") or "")[:500],
                "published_at": a.get("published_at"),
                "source":      a.get("source_name", ""),
            }
            for a in batch
        ], ensure_ascii=False, indent=2)

        return [{"role": "user", "content": f"Classify these {len(batch)} articles:\n\n{articles_json}"}]

    def validate_output(self, raw: str) -> list:
        # ── Attempt 1: full parse ─────────────────────────────────────────
        data = None
        try:
            data = self.parse_json(raw)
        except Exception as e:
            log.warning(f"[classifier] Full JSON parse failed: {e} — trying partial recovery")

        # ── Attempt 2: extract complete objects from partial/truncated JSON ─
        if data is None or not isinstance(data, list):
            import re
            objects = re.findall(r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}', raw, re.DOTALL)
            data = []
            for obj_str in objects:
                try:
                    data.append(json.loads(obj_str))
                except Exception:
                    pass
            if data:
                log.warning(f"[classifier] Recovered {len(data)} objects via partial parse")
            else:
                log.error(f"[classifier] Could not recover any objects. Raw (200): {raw[:200]}")
                return []

        valid = []
        for item in data:
            if not item.get("article_id"):
                log.warning("Classifier: item missing article_id — skipping")
                continue
            if not item.get("is_crisis"):
                valid.append(item)
                continue
            # FIX-10: remap GLOBAL/placeholder primary_country to first real country
            if item.get("primary_country") in ("GLOBAL", "XX", "XG", "INT", "UN", "EU", "NATO", "INTL", "G7", "G20", "OPEC", "ASEAN", ""):
                countries = item.get("countries_involved") or []
                real = next(
                    (c.get("code") for c in countries
                     if c.get("code") and c["code"] not in ("GLOBAL","XX","XG","INT","UN","EU","NATO","INTL","G7","G20","OPEC","ASEAN","")),
                    None
                )
                if real:
                    log.info(f"[classifier] GLOBAL primary_country remapped to {real}")
                    item["primary_country"] = real
                else:
                    log.warning("[classifier] GLOBAL primary_country with no real country — skipping")
                    continue
            if item.get("type") not in VALID_CRISIS_TYPES:
                bad_type = item.get("type")
                log.warning(f"Unknown type '{bad_type}' — skipping")  # FIX R-08
                continue
            sev = item.get("severity")
            if not isinstance(sev, int) or not (1 <= sev <= 10):
                log.warning(f"Invalid severity '{sev}' — skipping")
                continue
            valid.append(item)

        return valid

    def save(self, classified: list) -> None:
        now = datetime.now(timezone.utc).isoformat()

        for item in classified:
            article_id = item.get("article_id")

            if not item.get("is_crisis"):
                try:
                    self.db.table("raw_articles").update({"status": "filtered"}).eq("id", article_id).execute()
                except Exception as e:
                    log.warning(f"Could not update article status to filtered: {e}")
                continue

            row = {
                "id":              str(uuid.uuid4()),
                "article_id":      article_id,
                "crisis_id":       None,
                "title_clean":     item.get("title_clean", ""),
                "summary":         item.get("summary", ""),
                "severity":        item.get("severity"),
                "severity_reason": item.get("severity_reasoning", ""),
                "event_type":      item.get("type"),
                "sub_type":        item.get("sub_type"),
                "countries_inv":   item.get("countries_involved", []),
                "event_location":  item.get("event_location"),
                "primary_country": item.get("primary_country"),
                "keywords":        item.get("keywords", []),
                "media_attention": item.get("media_attention", "medium"),
                "real_impact":     item.get("real_impact", "medium"),
                "published_at":    self._get_article_date(article_id),
                "classified_at":   now,
            }
            try:
                self.db.table("classified_events").insert(row).execute()
                self.db.table("raw_articles").update({"status": "classified"}).eq("id", article_id).execute()
            except Exception as e:
                log.error(f"Failed to save classified event: {e}")

    def _get_article_date(self, article_id: str) -> str | None:
        try:
            result = (self.db.table("raw_articles")
                      .select("published_at")
                      .eq("id", article_id)
                      .single()
                      .execute())
            return result.data.get("published_at") if result.data else None
        except Exception:
            return None

    def run(self) -> bool:
        """FIX R-01: unified run() with audit — replaces monkey-patch."""
        if not self.check_data():
            log.info("[classifier] No new articles. Skipping.")
            return False

        total_articles = self.articles[:]
        processed = 0

        while processed < len(total_articles):
            self.articles = total_articles[processed:processed + 15]
            messages  = self.build_prompt()
            raw       = self.call_llm(messages, system=SYSTEM_PROMPT)
            validated = self.validate_output(raw)

            # Sonnet audit of this batch
            audited = self._audit_batch(validated)
            self.save(audited)
            processed += len(self.articles)  # FIX R-01: was hardcoded 15

        log.info(f"[classifier] Done. Processed {len(total_articles)} articles.")
        return True


    def _audit_batch(self, classified: list) -> list:
        """Sonnet audit: sends events, receives only corrections (not full copy).
        Much smaller response = no truncation issues."""
        import json as _json
        crisis_items = [item for item in classified if item.get("is_crisis")]
        non_crisis   = [item for item in classified if not item.get("is_crisis")]

        if not crisis_items:
            return classified

        # Build compact input — only fields Sonnet needs to audit
        compact = [
            {
                "article_id":      item.get("article_id"),
                "title_clean":     item.get("title_clean", ""),
                "summary":         item.get("summary", "")[:150],
                "severity":        item.get("severity"),
                "type":            item.get("type"),
                "primary_country": item.get("primary_country"),
            }
            for item in crisis_items
        ]

        try:
            response = self.client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=1024,  # corrections-only format is very small
                system=CLASSIFIER_VALIDATOR_SYSTEM,
                messages=[{
                    "role": "user",
                    "content": f"Audit these {len(compact)} events:\n\n{_json.dumps(compact, ensure_ascii=False)}"
                }],
            )
            from utils import track
            from config import MODEL_SONNET
            track(MODEL_SONNET, response.usage.input_tokens, response.usage.output_tokens, label="classifier_validator")

            raw = next((b.text for b in response.content if b.type == "text"), "")
            try:
                audit = self.parse_json(raw)
            except Exception as e:
                log.warning(f"[classifier] Audit parse failed: {e} — using original")
                return classified

            if not isinstance(audit, dict):
                return classified

            # Apply corrections to original items
            corrections = audit.get("corrections") or []
            removals    = set(audit.get("removals") or [])
            corrected_map = {}
            for c in corrections:
                aid = c.get("article_id")
                if aid:
                    corrected_map.setdefault(aid, []).append(c)

            result = []
            for item in crisis_items:
                aid = item.get("article_id")
                if aid in removals:
                    log.info(f"[classifier] Removed by audit: {item.get('title_clean', '')[:60]}")
                    # Convert to non-crisis instead of dropping entirely
                    item["is_crisis"] = False
                    result.append(item)
                    continue
                if aid in corrected_map:
                    for fix in corrected_map[aid]:
                        field = fix.get("field")
                        new_val = fix.get("new")
                        if not field or new_val is None:
                            continue
                        if field not in item:
                            log.debug(f"[classifier] Audit referenced unknown field '{field}' — skipping correction")
                            continue
                        # Validate type against DB constraint
                        if field == "type" and new_val not in VALID_CRISIS_TYPES:
                            log.warning(f"[classifier] Audit suggested invalid type '{new_val}' — skipping correction")
                            continue
                        # Validate severity range
                        if field == "severity":
                            if not isinstance(new_val, (int, float)) or not (1 <= int(new_val) <= 10):
                                log.warning(f"[classifier] Audit suggested invalid severity '{new_val}' — skipping")
                                continue
                            new_val = int(new_val)
                        old_val = item[field]
                        item[field] = new_val
                        log.info(f"[classifier] Correction: {field} {old_val}→{new_val} ({fix.get('reason', '')})")
                result.append(item)

            return result + non_crisis

        except Exception as e:
            log.warning(f"[classifier] Batch audit failed: {e} — using original output")

        return classified
