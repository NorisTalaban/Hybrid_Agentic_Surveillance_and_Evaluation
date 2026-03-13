"""
agents/agent_04_connector.py — Agent 04: CONNECTOR
Detects country-to-country relationships for active crises.
REGENERATION model: full diff each run.

FIX: uses MODEL_HAIKU (structured/mechanical task)

FIXES:
  - FIX-03: pre_save_validate() is now a clean override in the class
  - FIX-04: removed monkey-patching of _connector_pre_save_validate
  - FIX-11: BATCH_SIZE moved to __init__ as self.batch_size
"""

import uuid
import json
from datetime import datetime, timezone
from agents.base_agent import BaseAgent
from config import MODEL_HAIKU, MODEL_SONNET, CONNECTION_TYPES
from utils import get_client, get_logger, track

log = get_logger("connector")

SYSTEM_PROMPT = """You are a geopolitical relationship analyst.
You analyze active crises and identify country-to-country relationships.

Connection types:
  military_attack   — armed attack between countries
  sanction          — economic/diplomatic sanction
  trade_cut         — trade disruption or embargo
  aid               — humanitarian or military aid
  alliance          — political/military alliance
  disruption        — supply chain or infrastructure disruption
  refugee_flow      — population displacement across borders
  diplomatic_break  — breaking of diplomatic relations

For each connection, specify:
  - from_country, to_country (ISO 2-letter codes)
  - relation_type (from list above)
  - strength (1-10)
  - direction: "unidirectional" or "bidirectional"
  - description: one sentence

Return ONLY a JSON array of ALL CURRENT connections:
[
  {
    "crisis_id": "uuid",
    "from_country": "RU",
    "to_country": "UA",
    "relation_type": "military_attack",
    "strength": 10,
    "direction": "unidirectional",
    "description": "Russia conducting full-scale military invasion of Ukraine"
  }
]

Include ONLY connections that are currently active and significant.
Return ONLY valid JSON. No preamble.

CRITICAL: Your entire response must be a single JSON array starting with [ and ending with ].
Do NOT include any markdown, headers, explanations, or text outside the JSON.
Do NOT use ```json fences. Return raw JSON only."""

CONNECTOR_VALIDATOR_SYSTEM = """You are a geopolitical connections auditor.

You receive a list of country-to-country connections generated for active crises.
For EACH connection verify:
  1. Is this connection currently ACTIVE and real (not historical or hypothetical)?
  2. Is the relation_type correct? (military_attack vs sanction vs aid etc.)
  3. Is the direction correct? (who is acting on whom)
  4. Is the strength (1-10) realistic?

Remove connections that are:
  - Outdated (ceasefire signed, sanctions lifted, aid stopped)
  - Incorrect type (e.g. labelled military_attack when it's actually sanctions)
  - Too weak to be significant (strength < 3 unless strategically important)
  - Duplicate of another connection in the same list

Return ONLY a JSON array of validated connections (same structure):
[
  {
    "crisis_id": "...",
    "from_country": "RU",
    "to_country": "UA",
    "relation_type": "military_attack",
    "strength": 10,
    "direction": "unidirectional",
    "description": "...",
    "_validation_note": "confirmed active / corrected strength from 3 to 7"
  }
]

Be precise. Return ONLY valid JSON. No preamble."""


class ConnectorAgent(BaseAgent):

    def __init__(self):
        super().__init__(model=MODEL_HAIKU, agent_name="connector")
        self.db         = get_client()
        self.crises     = []
        self.batch_size = 10  # FIX-11: was class attribute, now in __init__

    def check_data(self) -> bool:
        result = (self.db.table("crises")
                  .select("id, name, type, countries, summary")
                  .neq("status", "resolved")
                  .execute())
        self.crises = result.data or []
        return len(self.crises) > 0

    def build_prompt(self) -> list[dict]:
        compact = [
            {
                "crisis_id": c["id"],
                "name":      c["name"],
                "type":      c["type"],
                "countries": c.get("countries", []),
                "summary":   (c.get("summary") or "")[:200],
            }
            for c in self.crises
        ]
        content = (
            f"Analyze these {len(compact)} active crises and return ALL current "
            f"country-to-country connections:\n\n{json.dumps(compact, ensure_ascii=False, indent=2)}"
        )
        return [{"role": "user", "content": content}]

    def validate_output(self, raw: str) -> list:
        import re
        json_matches = re.findall(r'\[[\s\S]*\]', raw, re.DOTALL)
        data = None
        for candidate in reversed(json_matches):
            try:
                parsed = json.loads(candidate)
                if isinstance(parsed, list):
                    data = parsed
                    break
            except json.JSONDecodeError:
                continue

        if data is None:
            data = self.parse_json(raw)

        if not isinstance(data, list):
            raise ValueError("Connector output must be a JSON array")

        valid = []
        for conn in data:
            if conn.get("relation_type") not in CONNECTION_TYPES:
                log.warning(f"Unknown relation_type: {conn.get('relation_type')} -- skipping")
                continue
            if not conn.get("crisis_id") or not conn.get("from_country") or not conn.get("to_country"):
                continue
            valid.append(conn)
        return valid

    def pre_save_validate(self, connections: list) -> list:
        """FIX-03 + FIX-04: Sonnet audit is now a clean override, not a monkey-patch."""
        if not connections:
            return connections
        try:
            response = self.client.messages.create(
                model=MODEL_SONNET,
                max_tokens=2000,
                system=CONNECTOR_VALIDATOR_SYSTEM,
                messages=[{
                    "role": "user",
                    "content": (
                        f"Audit these {len(connections)} connections:\n\n"
                        f"{json.dumps(connections, ensure_ascii=False, indent=2)}"
                    )
                }],
            )
            track(MODEL_SONNET, response.usage.input_tokens,
                  response.usage.output_tokens, label="connector_validator")

            raw = next((b.text for b in response.content if b.type == "text"), "")
            audited = self.parse_json(raw)
            if isinstance(audited, list):
                removed = len(connections) - len(audited)
                if removed:
                    log.info(f"[connector] Validator removed {removed} connections")
                for c in audited:
                    note = c.pop("_validation_note", "")
                    if note:
                        log.info(f"[connector] {c.get('from_country')}→{c.get('to_country')}: {note}")
                return audited
        except Exception as e:
            log.warning(f"[connector] pre_save_validate failed: {e} — using original output")
        return connections

    def save(self, new_connections: list) -> None:
        now = datetime.now(timezone.utc).isoformat()

        try:
            result   = self.db.table("connections").select("*").eq("active", True).execute()
            existing = result.data or []
        except Exception as e:
            log.error(f"Failed to load existing connections: {e}")
            existing = []

        def key(c):
            return f"{c['crisis_id']}:{c['from_country']}:{c['to_country']}:{c['relation_type']}"

        existing_map = {key(c): c for c in existing}
        new_map      = {key(c): c for c in new_connections}
        inserted = updated = deactivated = 0

        for k, conn in new_map.items():
            try:
                if k in existing_map:
                    self.db.table("connections").update({"last_seen": now}).eq("id", existing_map[k]["id"]).execute()
                    updated += 1
                else:
                    self.db.table("connections").insert({
                        "id":            str(uuid.uuid4()),
                        "crisis_id":     conn["crisis_id"],
                        "from_country":  conn["from_country"],
                        "to_country":    conn["to_country"],
                        "relation_type": conn["relation_type"],
                        "strength":      conn.get("strength", 5),
                        "direction":     conn.get("direction", "unidirectional"),
                        "description":   conn.get("description", ""),
                        "active":        True,
                        "first_seen":    now,
                        "last_seen":     now,
                    }).execute()
                    inserted += 1
            except Exception as e:
                log.error(f"Failed to upsert connection {k}: {e}")

        for k, old in existing_map.items():
            if k not in new_map:
                try:
                    self.db.table("connections").update({"active": False}).eq("id", old["id"]).execute()
                    deactivated += 1
                except Exception as e:
                    log.error(f"Failed to deactivate connection {old['id']}: {e}")

        log.info(f"Connector: +{inserted} new, ~{updated} updated, -{deactivated} deactivated")

    def run(self) -> bool:
        """FIX-04: run() is now a class method, not inherited via monkey-patch."""
        self.log.info(f"[{self.name}] Starting...")

        if not self.check_data():
            self.log.info(f"[{self.name}] No data to process. Skipping.")
            return False

        all_crises = self.crises[:]
        total      = len(all_crises)
        all_connections: list = []

        self.log.info(f"[{self.name}] Analyzing {total} crises in batches of {self.batch_size}...")

        processed = 0
        while processed < total:
            batch = all_crises[processed:processed + self.batch_size]
            self.crises = batch
            self.log.info(
                f"[{self.name}] Batch {processed // self.batch_size + 1}: "
                f"{len(batch)} crises ({processed + 1}-{processed + len(batch)} of {total})"
            )
            messages = self.build_prompt()
            for attempt in range(2):
                try:
                    raw       = self.call_llm(messages, system=SYSTEM_PROMPT)
                    validated = self.validate_output(raw)
                    all_connections.extend(validated)
                    break
                except (ValueError, json.JSONDecodeError) as e:
                    if attempt == 0:
                        self.log.warning(f"[{self.name}] Batch parse failed, retrying: {e}")
                    else:
                        self.log.error(f"[{self.name}] Batch failed after retry: {e}")
            processed += len(batch)

        self.crises = all_crises  # restore full list

        # FIX-03: pre_save_validate is now actually called
        try:
            all_connections = self.pre_save_validate(all_connections)
        except ValueError as e:
            self.log.error(f"[{self.name}] pre_save_validate rejected output: {e}")
            return False

        self.save(all_connections)
        self.log.info(f"[{self.name}] Done.")
        return True
