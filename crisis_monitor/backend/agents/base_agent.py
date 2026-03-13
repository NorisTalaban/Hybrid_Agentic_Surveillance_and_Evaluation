"""
agents/base_agent.py — BaseAgent template for all LLM agents

Lifecycle: check_data() -> build_prompt() -> call_llm() -> validate_output() -> pre_save_validate() -> save()

pre_save_validate() is the new Sonnet self-validation step before saving.
Each agent implements its own. Default: noop (passes everything through).

FIXES:
  - FIX-01: added parse_json_array() — was called by ScannerAgent but didn't exist
  - FIX-02: call_llm() now handles tool_use multi-turn (web_search)
             without this, Scanner and Verifier received intermediate text instead
             of the model's final response
"""

import json
import time
import anthropic
from abc import ABC, abstractmethod
from config import ANTHROPIC_API_KEY, MAX_TOKENS, MODEL_SONNET
from utils import get_logger, track

PRE_VALIDATE_MAX_TOKENS = 1024  # short responses, judgments only


class BaseAgent(ABC):

    def __init__(self, model: str, agent_name: str):
        self.model  = model
        self.name   = agent_name
        self.log    = get_logger(agent_name)
        self.client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    # ── Abstract interface ────────────────────────────────────────────────

    @abstractmethod
    def check_data(self) -> bool:
        """Return True if there is data to process."""
        ...

    @abstractmethod
    def build_prompt(self) -> list[dict]:
        """Return the messages list for the API call."""
        ...

    @abstractmethod
    def validate_output(self, raw: str) -> dict:
        """Parse and validate LLM output. Raise ValueError on bad output."""
        ...

    @abstractmethod
    def save(self, validated: dict) -> None:
        """Persist results to Supabase."""
        ...

    # ── Pre-save Sonnet validation (override in each agent) ───────────────

    def pre_save_validate(self, validated):
        """
        Sonnet self-validation before saving.
        Receives the validated output of the current run.
        Returns filtered/corrected output — or raises ValueError to abort.

        Default: passthrough. Override in each agent with specific logic.
        """
        return validated

    def _call_validator(self, system: str, user_content: str) -> dict:
        """
        Helper: single Sonnet call for pre-save validation.
        Returns parsed JSON dict. Raises ValueError on failure.
        """
        try:
            response = self.client.messages.create(
                model=MODEL_SONNET,
                max_tokens=PRE_VALIDATE_MAX_TOKENS,
                system=system,
                messages=[{"role": "user", "content": user_content}],
            )
            track(
                MODEL_SONNET,
                response.usage.input_tokens,
                response.usage.output_tokens,
                label=f"{self.name}_validator",
            )
            for block in response.content:
                if block.type == "text":
                    return self.parse_json(block.text)
            raise ValueError("Validator returned no text block")
        except Exception as e:
            self.log.warning(f"[{self.name}] pre_save_validate failed: {e} — proceeding without validation")
            return None

    # ── Shared call logic ─────────────────────────────────────────────────

    def call_llm(self, messages: list[dict], system: str = "", tools: list = None,
                 max_retries: int = 4) -> str:
        """
        Call the LLM with retry logic for rate limits and overload errors.

        FIX-02: Now handles tool_use multi-turn correctly.
        When the model uses web_search, the API returns stop_reason="tool_use"
        and we must continue the conversation with the tool results appended.
        Without this loop, Scanner and Verifier would receive intermediate
        text blocks instead of the final synthesized response.
        """
        kwargs = dict(
            model=self.model,
            max_tokens=MAX_TOKENS,
            messages=list(messages),  # copy to avoid mutating caller's list
        )
        if system:
            kwargs["system"] = system
        if tools:
            kwargs["tools"] = tools

        for attempt in range(max_retries):
            try:
                # ── FIX-02: web_search server-side handling ───────────────
                # web_search_20250305 is executed entirely server-side by Anthropic
                # The client may receive stop_reason="pause_turn"
                # if the model does multiple searches and needs to continue.
                # In that case we re-send the response as an assistant turn and
                # let the model finish.
                while True:
                    response = self.client.messages.create(**kwargs)

                    track(
                        self.model,
                        response.usage.input_tokens,
                        response.usage.output_tokens,
                        label=self.name
                    )

                    if response.stop_reason == "pause_turn":
                        # The model has performed web searches but needs to continue.
                        # Re-send content as assistant turn to let it continue.
                        kwargs["messages"] = kwargs["messages"] + [
                            {"role": "assistant", "content": response.content},
                        ]
                        continue  # loop: let the model finish

                    # stop_reason == "end_turn" — collect the final text
                    # With web_search the text block is always the last one
                    for block in reversed(response.content):
                        if block.type == "text":
                            return block.text

                    raise ValueError(
                        f"[{self.name}] LLM response contained no text blocks. "
                        f"Block types: {[b.type for b in response.content]}"
                    )

            except anthropic.RateLimitError:
                wait = 90 * (attempt + 1)
                self.log.warning(
                    f"[{self.name}] Rate limit hit (attempt {attempt+1}/{max_retries}). "
                    f"Waiting {wait}s..."
                )
                time.sleep(wait)
                if attempt == max_retries - 1:
                    raise

            except anthropic.APIStatusError as e:
                if e.status_code == 529:
                    wait = 30 * (attempt + 1)
                    self.log.warning(f"[{self.name}] API overloaded. Waiting {wait}s...")
                    time.sleep(wait)
                    if attempt == max_retries - 1:
                        raise
                else:
                    raise

        raise RuntimeError(f"[{self.name}] All {max_retries} retries exhausted")

    def parse_json(self, raw: str) -> dict | list:
        """Strip markdown fences and parse JSON."""
        import re
        cleaned = raw.strip()
        if not cleaned:
            raise ValueError("LLM returned empty response")
        if cleaned.startswith("```"):
            cleaned = re.sub(r'^```(?:json)?\s*', '', cleaned)
            cleaned = re.sub(r'\s*```$', '', cleaned)
        try:
            return json.loads(cleaned.strip())
        except json.JSONDecodeError:
            json_match = re.search(r'(\[[\s\S]*\]|\{[\s\S]*\})', raw)
            if json_match:
                return json.loads(json_match.group(1))
            raise ValueError(f"Could not parse JSON from LLM response (first 200 chars): {raw[:200]}")

    def parse_json_array(self, raw: str) -> list:
        """FIX-01: Parse JSON and assert result is a list. Used by ScannerAgent."""
        result = self.parse_json(raw)
        if not isinstance(result, list):
            raise ValueError(f"Expected JSON array, got {type(result).__name__}: {raw[:200]}")
        return result

    # ── Main entry point ──────────────────────────────────────────────────

    def run(self) -> bool:
        self.log.info(f"[{self.name}] Starting...")

        if not self.check_data():
            self.log.info(f"[{self.name}] No data to process. Skipping.")
            return False

        messages  = self.build_prompt()
        raw       = self.call_llm(messages)
        validated = self.validate_output(raw)

        # ── Pre-save Sonnet validation ────────────────────────────────────
        try:
            validated = self.pre_save_validate(validated)
        except ValueError as e:
            self.log.error(f"[{self.name}] pre_save_validate rejected output: {e}")
            return False

        self.save(validated)
        self.log.info(f"[{self.name}] Done.")
        return True
