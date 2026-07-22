"""
ingestion.py
Everything that happens when a new resource enters Kramly: hash it,
dedupe it, store it, create its graph node, and tag it with the skills
it covers.

Consolidated from the former ingestion.py + concept_extraction.py - the
first stage (hash/store/create-node) and the second stage (LLM concept
tagging) always run back-to-back on the same upload (see
api/routes.py::upload_resource), so keeping them in one file matches how
they're actually used.
"""

import hashlib
import uuid
from datetime import datetime, timezone

from marketplace.storage import get_storage_backend
from agent.llm_client import LLMUnavailableError, build_default_client


# ---------------------------------------------------------------------------
# Stage 1: hashing, duplicate detection, storage, Resource node creation
# ---------------------------------------------------------------------------

def compute_content_hash(content: bytes) -> str:
    """SHA-256 hex digest of the raw content."""
    return hashlib.sha256(content).hexdigest()


def check_exact_duplicate(tx, content_hash: str):
    """
    Returns a list of existing Resource records with the same content_hash,
    if any. Empty list means no exact duplicate found.
    """
    query = """
    MATCH (r:Resource {content_hash: $content_hash})
    RETURN r.id AS id, r.title AS title, r.upload_date AS upload_date
    """
    result = tx.run(query, content_hash=content_hash)
    return [dict(record) for record in result]


def ingest_resource(tx, title: str, resource_type: str, author_id: str, content: bytes,
                     resource_id: str = None, allow_duplicate: bool = False):
    """
    Full ingestion flow:
      1. Compute content hash
      2. Check for exact duplicates (raises unless allow_duplicate=True)
      3. Save content via the configured storage backend
      4. Create Resource + Author nodes and link them

    Returns the created resource's id and storage_key.

    NOTE on resource_type: no validation against the documented enum
    (note/project/flashcard/interview_experience/research_summary) is
    enforced here - add that check yourself if you want strict validation,
    since silently rejecting a type you may want to add later isn't ideal.
    """
    if resource_id is None:
        resource_id = str(uuid.uuid4())

    content_hash = compute_content_hash(content)

    duplicates = check_exact_duplicate(tx, content_hash)
    if duplicates and not allow_duplicate:
        raise ValueError(
            f"Exact duplicate content detected. Matches existing resource(s): "
            f"{[d['id'] for d in duplicates]}. Pass allow_duplicate=True to ingest anyway."
        )

    storage = get_storage_backend()
    storage_key = f"resources/{resource_id}"
    storage.save(storage_key, content)

    upload_date = datetime.now(timezone.utc).isoformat()

    query = """
    MERGE (a:Author {id: $author_id})
    MERGE (r:Resource {id: $resource_id})
    SET r.title = $title,
        r.type = $resource_type,
        r.author_id = $author_id,
        r.upload_date = $upload_date,
        r.content_hash = $content_hash,
        r.storage_key = $storage_key,
        r.status = 'active'
    MERGE (r)-[:AUTHORED_BY]->(a)
    """
    tx.run(
        query,
        author_id=author_id,
        resource_id=resource_id,
        title=title,
        resource_type=resource_type,
        upload_date=upload_date,
        content_hash=content_hash,
        storage_key=storage_key,
    )

    return {"resource_id": resource_id, "storage_key": storage_key, "content_hash": content_hash}


# ---------------------------------------------------------------------------
# Stage 2: concept extraction - link the resource to the skills it covers
# ---------------------------------------------------------------------------
# Uses the shared agent.llm_client (Groq primary, Mistral fallback) rather
# than a local Ollama call. Falls back to heuristic keyword matching if no
# LLM provider is configured or reachable.
#
# DESIGN CHOICE - GROUNDING: the LLM is given the actual list of existing
# skill IDs/names from the graph and asked to match against THAT list,
# rather than freely naming skills. This avoids the model inventing skill
# names that don't exist in your graph. A second, explicit filter below
# also strips any skill_id the model proposed that isn't in the valid
# list, since grounding via the prompt doesn't guarantee compliance.

EXTRACTION_SYSTEM_PROMPT = (
    "You link educational resources to the skills they cover. You will be given a list of "
    "VALID skill IDs and names - you may ONLY reference skills from that list, never invent "
    'new ones. Reply with ONLY JSON: {"matches": [{"skill_id": "<id from valid list>", '
    '"relevance_score": 0.0-1.0, "evidence_snippet": "<short quote from the resource text>"}]}. '
    "If the resource covers none of the valid skills, return an empty matches list."
)


def get_all_skills(tx):
    """Retrieves all existing skill IDs and names, for grounding the LLM prompt."""
    query = "MATCH (s:Skill) RETURN s.id AS id, s.name AS name"
    result = tx.run(query)
    return [dict(record) for record in result]


def format_skill_list(skills):
    return "\n".join(f"- {s['id']}: {s['name']}" for s in skills)


def call_llm_for_concept_extraction(resource_text: str, skills: list, llm_client=None):
    skill_list_str = format_skill_list(skills)
    user_prompt = f"VALID SKILLS:\n{skill_list_str}\n\nRESOURCE TEXT:\n{resource_text}"

    client = llm_client or build_default_client()

    if client.has_any_provider:
        try:
            from app.config import settings
            result = client.complete_json(
                EXTRACTION_SYSTEM_PROMPT, user_prompt,
                temperature=settings.llm_extraction_temperature,
                max_tokens=settings.llm_extraction_max_tokens,
            )
            candidates = result.get("matches", [])
            if not isinstance(candidates, list):
                candidates = []
        except LLMUnavailableError as e:
            print(f"WARNING: LLM concept extraction failed or was unavailable ({e}). Falling back to simple heuristic matching.")
            candidates = _fallback_concept_extraction(resource_text, skills)
    else:
        candidates = _fallback_concept_extraction(resource_text, skills)

    # Extra safety: filter out any skill_id the model hallucinated despite
    # instructions, since grounding in the prompt doesn't GUARANTEE compliance.
    valid_ids = {s["id"] for s in skills}
    filtered = [c for c in candidates if c.get("skill_id") in valid_ids]

    if len(filtered) < len(candidates):
        print(f"WARNING: model proposed {len(candidates) - len(filtered)} skill_id(s) "
              f"not in the valid list - these were dropped, not silently kept.")

    return filtered


def _fallback_concept_extraction(resource_text: str, skills: list) -> list:
    """Heuristic matching fallback: checks if skill names appear in the resource text."""
    matches = []
    text_lower = resource_text.lower()
    for s in skills:
        name = s["name"].lower()
        if name and name in text_lower:
            idx = text_lower.find(name)
            start = max(0, idx - 30)
            end = min(len(resource_text), idx + len(name) + 30)
            snippet = resource_text[start:end].strip()
            matches.append({
                "skill_id": s["id"],
                "relevance_score": 0.8,
                "evidence_snippet": f"...{snippet}..."
            })
    return matches


def link_resource_to_concepts(tx, resource_id: str, concept_links: list):
    """
    Creates COVERS_CONCEPT relationships from an already-ingested Resource
    to Skill nodes, based on extraction results.
    """
    query = """
    UNWIND $links AS link
    MATCH (r:Resource {id: $resource_id})
    MATCH (s:Skill {id: link.skill_id})
    MERGE (r)-[c:COVERS_CONCEPT]->(s)
    SET c.relevance_score = link.relevance_score,
        c.evidence_snippet = link.evidence_snippet
    """
    tx.run(query, resource_id=resource_id, links=concept_links)


def extract_and_link_concepts(tx, resource_id: str, resource_text: str, llm_client=None):
    """
    Full flow: fetch valid skills, call LLM, filter hallucinations, link
    approved concepts to the resource.

    NOTE: unlike Phase 3's prerequisite extraction, this does NOT require
    a separate human-review step before merging in the current design -
    COVERS_CONCEPT is a lower-stakes relationship than PREREQUISITE_OF
    (it doesn't change graph structure/ordering, just tags content).
    """
    skills = get_all_skills(tx)
    concept_links = call_llm_for_concept_extraction(resource_text, skills, llm_client=llm_client)
    link_resource_to_concepts(tx, resource_id, concept_links)
    return concept_links
