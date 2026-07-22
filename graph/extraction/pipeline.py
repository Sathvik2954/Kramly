"""
pipeline.py
-----------
End-to-end reference pipeline for turning free-text source material into
reviewed, Neo4j-loaded PREREQUISITE_OF edges. Merged from three previously
separate scripts (extract_candidates.py, review_cli.py, load_extracted.py)
since they're always run in sequence as one workflow, not independently.

Stages (run as subcommands from this directory):
    python pipeline.py extract   - LLM proposes candidate edges from source text -> candidate_edges.csv
    python pipeline.py review    - human CLI approves/rejects each candidate -> reviewed_approved.csv
    python pipeline.py load      - loads reviewed_approved.csv into Neo4j

Uses the project's shared agent.llm_client (Groq primary, Mistral fallback)
for the extract stage, NOT a local Ollama call - this was the one remaining
place in the project still calling Ollama directly, since it lives outside
backend/ and was missed during the earlier "Groq/Mistral only" pass.

Per the project's human-in-the-loop design principle, `extract` only ever
writes SUGGESTIONS to a CSV - nothing touches the graph until a human runs
`review` and then `load`.
"""

import csv
import os
import re
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_GRAPH_DIR = os.path.abspath(os.path.join(_HERE, ".."))
_BACKEND_DIR = os.path.abspath(os.path.join(_HERE, "..", "..", "backend"))
for _p in (_GRAPH_DIR, _BACKEND_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from db import get_driver  # graph/db.py - shared connection helper, Aura-ready

SOURCE_TEXT_PATH = os.path.join(_HERE, "example_source_text.md")
CANDIDATES_PATH = os.path.join(_HERE, "candidate_edges.csv")
APPROVED_PATH = os.path.join(_HERE, "reviewed_approved.csv")
DEFAULT_DOMAIN = "MobileAppDev"

EXTRACTION_SYSTEM_PROMPT = (
    "You are helping build a prerequisite skill graph for an educational platform. "
    "Identify pairs of concepts where one is a PREREQUISITE of the other - i.e. a learner "
    'should understand the first concept before the second. Reply with ONLY JSON: '
    '{"candidates": [{"from_skill": "concept name", "to_skill": "concept name", '
    '"confidence": 0.0-1.0, "source_snippet": "short quote from the text supporting this"}]}. '
    "If you find no clear prerequisite relationships, return an empty candidates list."
)


# ---------------------------------------------------------------------------
# Stage 1: extract - LLM proposes candidate edges from source text
# ---------------------------------------------------------------------------

def stage_extract():
    from agent.llm_client import build_default_client, LLMUnavailableError

    with open(SOURCE_TEXT_PATH, "r", encoding="utf-8") as f:
        source_text = f.read()
    print(f"Read {len(source_text)} characters from {SOURCE_TEXT_PATH}")

    client = build_default_client()
    if not client.has_any_provider:
        print("ERROR: no GROQ_API_KEY or MISTRAL_API_KEY configured. "
              "Set one in your .env before running the extract stage.")
        return

    try:
        from app.config import settings
        result = client.complete_json(
            EXTRACTION_SYSTEM_PROMPT, f"TEXT:\n{source_text}",
            max_tokens=settings.llm_graph_extraction_max_tokens,
        )
        candidates = result.get("candidates", [])
        if not isinstance(candidates, list):
            candidates = []
    except LLMUnavailableError as e:
        print(f"ERROR: LLM extraction failed: {e}")
        return

    print(f"Model proposed {len(candidates)} candidate prerequisite relationships.")

    with open(CANDIDATES_PATH, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["from_skill", "to_skill", "confidence", "source_snippet"])
        writer.writeheader()
        for c in candidates:
            writer.writerow({
                "from_skill": c.get("from_skill", ""),
                "to_skill": c.get("to_skill", ""),
                "confidence": c.get("confidence", ""),
                "source_snippet": c.get("source_snippet", ""),
            })

    print(f"Written to {CANDIDATES_PATH}")
    print("IMPORTANT: these are SUGGESTIONS ONLY. Run 'python pipeline.py review' next.")


# ---------------------------------------------------------------------------
# Stage 2: review - human CLI approves/rejects each candidate
# ---------------------------------------------------------------------------

def stage_review():
    if not os.path.exists(CANDIDATES_PATH):
        print(f"No candidates file found at {CANDIDATES_PATH}. Run 'python pipeline.py extract' first.")
        return

    with open(CANDIDATES_PATH, newline="", encoding="utf-8") as f:
        candidates = list(csv.DictReader(f))

    if not candidates:
        print("No candidates to review.")
        return

    approved = []
    for c in candidates:
        print("\n---")
        print(f"Proposed: '{c['from_skill']}' -> '{c['to_skill']}'")
        print(f"Confidence: {c['confidence']}")
        print(f"Source snippet: {c['source_snippet']}")
        decision = input("Approve this edge? (y/n): ").strip().lower()
        if decision == "y":
            approved.append(c)

    with open(APPROVED_PATH, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["from_skill", "to_skill", "confidence", "source_snippet"])
        writer.writeheader()
        writer.writerows(approved)

    print(f"\n{len(approved)} of {len(candidates)} candidates approved. Written to {APPROVED_PATH}")


# ---------------------------------------------------------------------------
# Stage 3: load - loads reviewed_approved.csv into Neo4j
# ---------------------------------------------------------------------------

def _slugify_name(name: str) -> str:
    """Generates a clean skill ID from its text name (e.g. 'Core Language' -> 'CORE_LANGUAGE')."""
    clean = re.sub(r"[^a-zA-Z0-9\s]", "", name).strip()
    return re.sub(r"\s+", "_", clean).upper()


def _load_edge_tx(tx, from_name, to_name, confidence):
    from_id = _slugify_name(from_name)
    to_id = _slugify_name(to_name)

    query = """
    MERGE (s:Skill {name: $from_name})
    ON CREATE SET s.id = $from_id,
                  s.domain = $domain,
                  s.difficulty_level = 'beginner'

    MERGE (t:Skill {name: $to_name})
    ON CREATE SET t.id = $to_id,
                  t.domain = $domain,
                  t.difficulty_level = 'intermediate'

    MERGE (s)-[r:PREREQUISITE_OF]->(t)
    SET r.confidence = $confidence
    RETURN s.id AS from_id, t.id AS to_id
    """
    result = tx.run(
        query,
        from_name=from_name,
        from_id=from_id,
        to_name=to_name,
        to_id=to_id,
        domain=DEFAULT_DOMAIN,
        confidence=float(confidence),
    )
    return result.single()


def stage_load():
    if not os.path.exists(APPROVED_PATH):
        print(f"[Error] Approved edges file not found at: {APPROVED_PATH}")
        print("Run 'python pipeline.py review' first to approve some relationship edges.")
        return

    try:
        driver = get_driver()
    except Exception as e:
        print(f"[Error] Failed to connect to Neo4j: {e}")
        return

    with open(APPROVED_PATH, newline="", encoding="utf-8") as f:
        edges = list(csv.DictReader(f))

    if not edges:
        print("No edges found in reviewed_approved.csv. Nothing to load.")
        driver.close()
        return

    print(f"Processing {len(edges)} approved prerequisite edges...")
    loaded_count = 0
    with driver.session() as session:
        for idx, edge in enumerate(edges, 1):
            from_name = edge.get("from_skill", "").strip()
            to_name = edge.get("to_skill", "").strip()
            confidence = edge.get("confidence", "1.0")

            if not from_name or not to_name:
                print(f"Skipping row {idx}: missing from_skill or to_skill.")
                continue

            try:
                res = session.execute_write(_load_edge_tx, from_name, to_name, confidence)
                if res:
                    print(f"[{idx}] Loaded: '{from_name}' ({res['from_id']}) -> '{to_name}' ({res['to_id']})")
                    loaded_count += 1
            except Exception as ex:
                print(f"[{idx}] Failed to load edge '{from_name}' -> '{to_name}': {ex}")

    driver.close()
    print(f"\n[Success] Loaded {loaded_count} prerequisite edges successfully into Neo4j.")


STAGES = {"extract": stage_extract, "review": stage_review, "load": stage_load}


def main():
    if len(sys.argv) < 2 or sys.argv[1] not in STAGES:
        print("Usage: python pipeline.py <extract|review|load>")
        print("  extract - LLM proposes candidate prerequisite edges from source text")
        print("  review  - human CLI approves/rejects each candidate")
        print("  load    - loads approved edges into Neo4j")
        return

    STAGES[sys.argv[1]]()


if __name__ == "__main__":
    main()
