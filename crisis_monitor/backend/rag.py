"""
rag.py — RAG (Retrieval-Augmented Generation) retriever for Crisis Monitor.

Loads academic knowledge base documents from /rag directory,
parses them into chunks, and retrieves relevant chunks based on
agent type, crisis type, status, and extra keywords.

CHANGES from original utils.py:
  - Extracted into its own module
  - _RagRetriever singleton is cleaner (no mutable class variables)
  - Added retrieve_raw() for programmatic use (returns chunks without formatting)
  - Keyword matching is case-insensitive throughout
"""

import re
from pathlib import Path
from logger import get_logger

_log = get_logger("rag_retriever")

RAG_DIR = Path(__file__).parent / "rag"

# Which RAG documents are primary for each agent
AGENT_PRIMARY = {
    "analyst":  ["RAG_01", "RAG_06"],
    "scanner":  ["RAG_03", "RAG_04", "RAG_05"],
    "verifier": ["RAG_02", "RAG_07", "RAG_08"],
    "matcher":  ["RAG_05", "RAG_06"],
}

# Keywords associated with crisis types
TYPE_KEYWORDS = {
    "conflict":  ["conflict", "military", "escalation", "armed", "war", "attack", "spiral",
                  "deterrence", "proxy", "spillover", "ceasefire"],
    "political": ["political", "elite", "polarization", "coup", "election", "leader",
                  "faction", "regime", "protest", "instability"],
    "disaster":  ["disaster", "panic", "crowd", "mass", "evacuation", "humanitarian",
                  "emergency", "flood", "earthquake", "response"],
    "economic":  ["economic", "sanction", "trade", "crisis", "financial", "recession"],
    "health":    ["health", "epidemic", "outbreak", "panic", "emergency", "mass"],
}

# Keywords associated with crisis statuses
STATUS_KEYWORDS = {
    "escalating":    ["escalation", "escalatory", "spiral", "armed", "increase"],
    "de_escalating": ["de-escalation", "ceasefire", "withdrawal", "resolution", "stabilize"],
    "stable":        ["stable conflict", "persistent", "chronic", "latent"],
    "active":        ["active", "ongoing", "warning signals", "early warning"],
    "resolved":      ["resolution", "post-crisis", "recovery", "learning"],
}


# ── Document and Chunk parsing ────────────────────────────────────────────────

class _RagDocument:
    """Represents a single RAG knowledge base file, parsed into chunks."""

    def __init__(self, path: Path):
        self.path        = path
        self.name        = path.stem
        self.short_name  = self.name[:6]
        self.agent_tag   = ""
        self.k_retrieval = 3
        self.source_line = ""
        self.chunks: list[dict] = []
        self._parse()

    def _parse(self):
        text  = self.path.read_text(encoding="utf-8")
        lines = text.splitlines()

        # Parse metadata from first 20 lines
        for line in lines[:20]:
            if "Primary agent:" in line:
                m = re.search(r"Primary agent:\s*(\w+)", line, re.IGNORECASE)
                if m:
                    self.agent_tag = m.group(1).lower()
                k = re.search(r"recommended k-retrieval:\s*(\d+)", line)
                if k:
                    self.k_retrieval = int(k.group(1))
            if line.startswith("Source:"):
                self.source_line = line.replace("Source:", "").strip()

        # Parse chunks (format: C01 | Chunk Title)
        chunk_pattern = re.compile(r'^(C\d{2})\s*\|\s*(.+)$', re.MULTILINE)
        matches = list(chunk_pattern.finditer(text))
        for i, match in enumerate(matches):
            chunk_id    = match.group(1)
            chunk_title = match.group(2).strip()
            start       = match.end()
            end         = matches[i + 1].start() if i + 1 < len(matches) else len(text)
            body        = text[start:end].strip()
            kw_match    = re.search(r'Keywords:\s*(.+)', body)
            keywords    = [k.strip().lower() for k in kw_match.group(1).split(",")] if kw_match else []
            self.chunks.append({
                "chunk_id":  chunk_id,
                "title":     chunk_title,
                "body":      body,
                "keywords":  keywords,
                "doc_name":  self.name,
                "agent_tag": self.agent_tag,
                "source":    self.source_line,
            })


# ── Retriever singleton ──────────────────────────────────────────────────────

class _RagRetriever:
    """Singleton retriever that loads and indexes all RAG documents."""

    _instance: "_RagRetriever | None" = None

    @classmethod
    def get(cls) -> "_RagRetriever":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self):
        self._docs: list[_RagDocument] = []
        if not RAG_DIR.exists():
            _log.warning(f"RAG directory not found: {RAG_DIR}")
            return
        txt_files  = sorted(RAG_DIR.glob("RAG_*.txt"))
        self._docs = [_RagDocument(f) for f in txt_files]
        total      = sum(len(d.chunks) for d in self._docs)
        _log.info(f"RAG: loaded {len(self._docs)} docs, {total} chunks")

    def retrieve(self, agent: str, crisis_type: str = "", status: str = "",
                 extra_keywords: list[str] = None, max_chunks: int = None) -> list[dict]:
        """
        Retrieve relevant chunks scored by:
          - Primary document match (+3)
          - Agent tag match (+1)
          - Crisis type keyword match (+2 each)
          - Status keyword match (+1 each)
          - Extra keyword match (+1 each)
        """
        agent    = agent.lower()
        primary  = AGENT_PRIMARY.get(agent, [])
        type_kw  = [k.lower() for k in TYPE_KEYWORDS.get(crisis_type, [])]
        stat_kw  = [k.lower() for k in STATUS_KEYWORDS.get(status, [])]
        extra_kw = [k.lower() for k in (extra_keywords or [])]

        scored = []
        for doc in self._docs:
            for chunk in doc.chunks:
                score = 0
                if any(chunk["doc_name"].startswith(p) for p in primary):
                    score += 3
                if chunk["agent_tag"] == agent:
                    score += 1
                text = (chunk["title"] + " " + chunk["body"]).lower()
                for kw in type_kw:
                    if kw in text:
                        score += 2
                for kw in stat_kw:
                    if kw in text:
                        score += 1
                for kw in extra_kw:
                    if kw in text:
                        score += 1
                if score > 0:
                    scored.append((score, chunk))

        scored.sort(key=lambda x: -x[0])

        # Deduplicate
        seen, results = set(), []
        for _, chunk in scored:
            key = f"{chunk['doc_name']}:{chunk['chunk_id']}"
            if key not in seen:
                seen.add(key)
                results.append(chunk)

        # Determine max_chunks from primary docs if not specified
        if max_chunks is None:
            primary_docs = [d for d in self._docs
                            if any(d.short_name.startswith(p) for p in primary)]
            max_chunks = sum(d.k_retrieval for d in primary_docs) if primary_docs else 5

        return results[:max_chunks]

    def format_for_prompt(self, agent: str, crisis_type: str = "", status: str = "",
                          extra_keywords: list[str] = None, max_chunks: int = None) -> str:
        """Retrieve chunks and format them as a text block for LLM prompts."""
        chunks = self.retrieve(agent, crisis_type, status, extra_keywords, max_chunks)
        if not chunks:
            return ""
        lines = [
            "=" * 60,
            "ACADEMIC KNOWLEDGE BASE — RELEVANT FRAMEWORKS",
            "Use these theoretical frameworks to enrich your analysis.",
            "=" * 60,
        ]
        for c in chunks:
            lines.append(f"\n[{c['doc_name']} — {c['chunk_id']}] {c['title']}")
            lines.append(f"Source: {c['source']}")
            # Strip the Keywords: line from the body before including
            lines.append(re.sub(r'\nKeywords:.*', '', c['body']).strip())
        lines.append("=" * 60)
        return "\n".join(lines)


# ── Public API ────────────────────────────────────────────────────────────────

def get_rag_context(agent: str, crisis_type: str = "", status: str = "",
                    extra_keywords: list[str] = None, max_chunks: int = None) -> str:
    """Get formatted RAG context for an LLM prompt."""
    return _RagRetriever.get().format_for_prompt(
        agent=agent, crisis_type=crisis_type, status=status,
        extra_keywords=extra_keywords, max_chunks=max_chunks,
    )


def get_rag_chunks(agent: str, crisis_type: str = "", status: str = "",
                   extra_keywords: list[str] = None, max_chunks: int = None) -> list[dict]:
    """Get raw RAG chunks (for programmatic use, not prompt injection)."""
    return _RagRetriever.get().retrieve(
        agent=agent, crisis_type=crisis_type, status=status,
        extra_keywords=extra_keywords, max_chunks=max_chunks,
    )
