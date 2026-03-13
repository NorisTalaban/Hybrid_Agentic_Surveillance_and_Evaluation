"""
agents/agent_00_scanner.py — Agent 00: SCANNER
Web search for active crises worldwide. Bootstrap + weekly modes.

CHANGES:
  - DECOUPLED: save() no longer calls ConnectorAgent.run() directly.
    The caller (bootstrap.py or run.py scan) is responsible for running Connector after Scanner.
    This prevents Connector failures from breaking Scanner's save flow.
  - Uses BaseAgent.parse_json_array() instead of custom regex parsing
  - Added duplicate-name check against existing DB crises (weekly mode)
"""

import json
from datetime import datetime, timezone
from agents.base_agent import BaseAgent
from utils import get_rag_context, get_client, get_logger, ValidatorC, SeedWriter
from config import MODEL_SONNET, RAG_MAX_CHUNKS_SCANNER

log = get_logger("scanner")

WEB_SEARCH_TOOL = {
    "type": "web_search_20250305",
    "name": "web_search",
}

_BASE_SYSTEM_PROMPT = """You are a global crisis intelligence analyst with web search access.

Search the web for CURRENTLY ACTIVE crises worldwide (last 3 months).
Do NOT include: historical/resolved crises, predictions, academic analyses.

Use web search EFFICIENTLY: do 3-4 broad searches covering different crisis types,
then synthesize results into a single JSON array.

For each crisis return:
{
  "name": "Sudan Civil War",
  "type": "conflict",
  "status": "active",
  "severity": 8,
  "countries": ["SD"],
  "summary": "One sentence current situation.",
  "started_at": "2023-04-15",
  "last_known_event": "2026-02-10",
  "key_timeline": [
    {"date": "2023-04-15", "title": "War begins", "significance": "RSF vs SAF clash"}
  ],
  "already_in_db": false,
  "possible_duplicate_of": null
}

CRITICAL DATE RULES:
  - started_at = when the CURRENT ACTIVE PHASE began, NOT the historical origin.
    Example: Myanmar Civil War current phase started 2021-02-01 (coup), NOT 1948.
    Example: Israel-Palestine current phase started 2023-10-07, NOT 1948.
  - last_known_event = most recent significant event you found (must be within last 3 months).
  - If you cannot determine a recent start date, use the best recent approximation.

Severity: 1-2 minor, 3-4 regional, 5-6 significant, 7-8 severe, 9-10 catastrophic
Types: conflict | disaster | economic | political | health

Rules:
- Find 15-20 active crises, severity >= 5
- Max 1-2 key_timeline entries per crisis (most important only)
- Summary: ONE short sentence max (under 20 words)
- No duplicates

Return ONLY a valid JSON array. No preamble."""


def _build_system_prompt() -> str:
    rag_context = get_rag_context(
        agent="scanner",
        extra_keywords=["early warning", "escalation", "warning signs"],
        max_chunks=RAG_MAX_CHUNKS_SCANNER,
    )
    return _BASE_SYSTEM_PROMPT + ("\n\n" + rag_context if rag_context else "")


class ScannerAgent(BaseAgent):

    def __init__(self, mode: str = "bootstrap"):
        super().__init__(model=MODEL_SONNET, agent_name="scanner")
        self.mode           = mode
        self.db             = get_client()
        self._system_prompt = _build_system_prompt()
        self._existing_names: set[str] = set()

    def check_data(self) -> bool:
        # FIX-07: _existing_names loaded here, not in build_prompt()
        # validate_output() depends on this set — loading it in build_prompt()
        # creates an implicit dependency on execution order.
        existing = self._get_existing_crises()
        self._existing_names = {c["name"].lower() for c in existing}
        return True

    def build_prompt(self) -> list[dict]:
        existing     = self._get_existing_crises()
        existing_str = json.dumps(existing, ensure_ascii=False) if existing else "[]"
        today        = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        content = f"""Today is {today}.

Search the web for ALL currently active global crises.
Cover: armed conflicts, natural disasters, political crises, economic crises, health emergencies.

Crises already in DB (skip these): {existing_str}

Find 15-20 active crises with severity >= 5. Keep summaries very short (under 20 words each).
Return ONLY a valid JSON array."""

        return [{"role": "user", "content": content}]

    def validate_output(self, raw: str) -> list:
        data = self.parse_json_array(raw)

        valid = []
        seen  = set()
        for item in data:
            if not isinstance(item, dict) or not item.get("name"):
                continue
            name = item["name"]
            # Skip duplicates within this response
            if name in seen:
                continue
            # Skip crises already in DB (weekly mode)
            if name.lower() in self._existing_names:
                log.debug(f"Scanner: skipping '{name}' — already in DB")
                continue
            missing = [f for f in ["name", "type", "severity", "countries", "summary"] if f not in item]
            if missing:
                log.warning(f"Scanner: skipping '{name}' — missing: {missing}")
                continue
            if "key_timeline" not in item:
                item["key_timeline"] = []
            seen.add(name)
            valid.append(item)

        log.info(f"Scanner: {len(valid)} valid crises found")
        return valid

    def save(self, crises: list) -> None:
        """
        Validate with ValidatorC and write to DB via SeedWriter.
        NOTE: does NOT call ConnectorAgent anymore — caller is responsible.
        """
        valid_crises = ValidatorC().run(crises)
        log.info(f"ValidatorC: {len(valid_crises)}/{len(crises)} passed")
        written = SeedWriter().write(valid_crises)
        log.info(f"SeedWriter: {written} new crises written to DB")

    def _get_existing_crises(self) -> list:
        if self.mode == "bootstrap":
            return []
        try:
            result = (self.db.table("crises")
                      .select("name, type, status")
                      .neq("status", "resolved")
                      .execute())
            return [{"name": r["name"], "type": r["type"]} for r in (result.data or [])]
        except Exception as e:
            log.warning(f"Could not load existing crises: {e}")
            return []

    def run(self) -> bool:
        self.log.info(f"[{self.name}] Starting (mode={self.mode})...")

        self.check_data()  # FIX R-02: populate _existing_names before build_prompt

        messages = self.build_prompt()

        try:
            raw    = self.call_llm(messages, system=self._system_prompt, tools=[WEB_SEARCH_TOOL])
            crises = self.validate_output(raw)
        except Exception as e:
            self.log.error(f"Scanner failed: {e}")
            return False

        self.save(crises)
        self.log.info(f"[{self.name}] Done.")
        return True
