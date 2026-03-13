"""
agents/agent_01_collector.py — Agent 01: COLLECTOR
Fetches news articles from GNews API. Python only, no LLM.
"""

import uuid
import time
import requests
from datetime import datetime, timezone
from agents.base_agent import BaseAgent
from config import GNEWS_API_KEY, GNEWS_QUERIES, GNEWS_LANG, GNEWS_RATE_LIMIT_SEC, ANTHROPIC_API_KEY
from utils import get_client
from utils import get_logger

log = get_logger("collector")

GNEWS_BASE = "https://gnews.io/api/v4"


class GNewsCollector(BaseAgent):

    def __init__(self):
        super().__init__(model=None, agent_name="collector")  # FIX-12: inherits from BaseAgent
        self.db        = get_client()
        self.now       = datetime.now(timezone.utc).isoformat()
        self.api_calls = 0
        self.new_count = 0

    # BaseAgent abstract stubs — GNewsCollector does not use BaseAgent's LLM cycle
    def check_data(self)          -> bool:       return True
    def build_prompt(self)        -> list:        return []
    def validate_output(self, r)  -> dict:        return {}
    def save(self, v)             -> None:        pass

    def run(self) -> int:
        """Run one collection cycle. Returns count of new articles saved."""
        if not GNEWS_API_KEY:
            log.error("Collector: GNEWS_API_KEY not set. Skipping collection.")
            return 0
        log.info("Collector: starting GNews collection...")

        existing_urls = self._load_existing_urls()

        for query, max_results in GNEWS_QUERIES:
            articles = self._fetch(query, max_results)
            for article in articles:
                url = article.get("url", "")
                if url and url not in existing_urls:
                    self._save_article(article, query)
                    existing_urls.add(url)
            time.sleep(GNEWS_RATE_LIMIT_SEC)

        self._log_collection()
        log.info(f"Collector done: {self.new_count} new articles from {self.api_calls} API calls")
        return self.new_count

    # ── Fetch ─────────────────────────────────────────────────────────────

    def _fetch(self, query: str, max_results: int) -> list:
        params = {
            "apikey": GNEWS_API_KEY,
            "lang":   GNEWS_LANG,
            "max":    max_results,
            "sortby": "publishedAt",
        }
        if query:
            params["q"] = query
            endpoint = f"{GNEWS_BASE}/search"
        else:
            endpoint = f"{GNEWS_BASE}/top-headlines"
            params["topic"] = "world"

        try:
            resp = requests.get(endpoint, params=params, timeout=10)
            resp.raise_for_status()
            self.api_calls += 1
            return resp.json().get("articles", [])
        except requests.RequestException as e:
            log.warning(f"GNews request failed (query='{query}'): {e}")
            return []

    # ── Save ──────────────────────────────────────────────────────────────

    def _save_article(self, a: dict, query_used: str):
        row = {
            "id":           str(uuid.uuid4()),
            "gnews_id":     a.get("url", ""),
            "title":        a.get("title", "")[:500],
            "description":  a.get("description", "")[:1000],
            "content":      a.get("content", "")[:3000],
            "url":          a.get("url", ""),
            "image_url":    a.get("image"),
            "source_name":  (a.get("source") or {}).get("name", ""),
            "source_url":   (a.get("source") or {}).get("url", ""),
            "published_at": a.get("publishedAt"),
            "collected_at": self.now,
            "query_used":   query_used,
            "status":       "new",
        }
        try:
            self.db.table("raw_articles").insert(row).execute()
            self.new_count += 1
        except Exception as e:
            log.debug(f"Skipped article (likely duplicate): {e}")

    def _load_existing_urls(self) -> set:
        try:
            # Only check last 7 days to avoid loading entire history
            from datetime import timedelta
            since = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
            result = (self.db.table("raw_articles")
                      .select("url")
                      .gte("collected_at", since)
                      .execute())
            return {r["url"] for r in (result.data or [])}
        except Exception as e:
            log.warning(f"Could not load existing URLs: {e}")
            return set()

    def _log_collection(self):
        try:
            self.db.table("cm_collection_log").insert({
                "run_type":       "enricher",
                "collected_at":   self.now,
                "articles_count": self.new_count,
                "api_calls_used": self.api_calls,
                "cost_estimate":  0.0,
            }).execute()
        except Exception as e:
            log.warning(f"Could not write cm_collection_log: {e}")


# ── Pre-save Sonnet validation ─────────────────────────────────────────────────

COLLECTOR_VALIDATOR_SYSTEM = """You are a crisis news relevance filter.

You receive a batch of news articles just fetched from GNews.
For EACH article decide: keep or discard.

Discard if:
- It's clearly not about an active geopolitical crisis (sports, entertainment, lifestyle, business earnings, tech product launches)
- It's an opinion piece or editorial with no factual crisis content
- It's a duplicate of another article in this batch (same event, different source)

Keep if:
- It describes an active conflict, disaster, political crisis, health emergency, or economic collapse
- It has a clear geographic location and real-world impact
- Even if minor or regional — real events count

Return ONLY a JSON object:
{
  "decisions": [
    {"url": "...", "keep": true, "reason": "active conflict in Sudan"},
    {"url": "...", "keep": false, "reason": "sports news"}
  ]
}

Be decisive. When in doubt about relevance, discard. Return ONLY valid JSON."""


class GNewsCollectorWithValidation(GNewsCollector):
    """Extends GNewsCollector with Sonnet pre-save validation."""

    def __init__(self):
        super().__init__()
        # FIX-12: uses self.client inherited from BaseAgent — no duplicate client
        from config import MODEL_SONNET
        self._val_model  = MODEL_SONNET
        self._discarded  = 0

    def run(self) -> int:
        """Override run to add batch validation before saving."""
        if not GNEWS_API_KEY:
            log.error("Collector: GNEWS_API_KEY not set. Skipping collection.")
            return 0
        log.info("Collector: starting GNews collection with Sonnet validation...")

        existing_urls = self._load_existing_urls()
        pending = []  # articles to validate before saving

        for query, max_results in GNEWS_QUERIES:
            articles = self._fetch(query, max_results)
            for article in articles:
                url = article.get("url", "")
                if url and url not in existing_urls:
                    pending.append(article)
                    existing_urls.add(url)
            time.sleep(GNEWS_RATE_LIMIT_SEC)

        if not pending:
            log.info("Collector: no new articles fetched.")
            self._log_collection()
            return 0

        # ── Sonnet validation in batches of 20 ───────────────────────────
        approved = self._validate_batch(pending)
        log.info(f"Collector: {len(approved)}/{len(pending)} approved by Sonnet "
                 f"({self._discarded} discarded)")

        for article in approved:
            self._save_article(article, article.get("_query_used", ""))

        self._log_collection()
        log.info(f"Collector done: {self.new_count} new articles saved")
        return self.new_count

    def _validate_batch(self, articles: list) -> list:
        """Ask Sonnet to filter irrelevant articles. Returns approved list."""
        import json
        BATCH = 20
        approved = []

        for i in range(0, len(articles), BATCH):
            batch = articles[i:i + BATCH]
            payload = [
                {
                    "url":         a.get("url", ""),
                    "title":       a.get("title", ""),
                    "description": (a.get("description") or "")[:300],
                }
                for a in batch
            ]
            try:
                response = self.client.messages.create(
                    model=self._val_model,
                    max_tokens=800,
                    system=COLLECTOR_VALIDATOR_SYSTEM,
                    messages=[{
                        "role": "user",
                        "content": f"Validate these {len(batch)} articles:\n\n{json.dumps(payload, ensure_ascii=False, indent=2)}"
                    }],
                )
                raw = next((b.text for b in response.content if b.type == "text"), "")
                result = json.loads(raw.strip())
                decisions = {d["url"]: d["keep"] for d in result.get("decisions", [])}

                for article in batch:
                    url = article.get("url", "")
                    if decisions.get(url, True):  # default keep if missing
                        approved.append(article)
                    else:
                        self._discarded += 1
                        log.debug(f"Discarded: {article.get('title', '')[:60]}")

            except Exception as e:
                log.warning(f"Collector validator failed for batch {i}: {e} — keeping all")
                approved.extend(batch)

        return approved
