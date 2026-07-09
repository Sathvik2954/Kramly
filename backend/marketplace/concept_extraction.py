"""
concept_extraction.py
Phase 5, Person A — concept extraction: identify which existing Skill
nodes a Resource covers, and link via COVERS_CONCEPT.

Reuses the same Ollama-based extraction pattern from Phase 3's
extract_candidates.py. Same uncertainty flags apply here — verify
ollama.chat()'s exact call/response shape against current docs.

DESIGN CHOICE — GROUNDING: the LLM is given the actual list of existing
skill IDs/names from the graph and asked to match against THAT list,
rather than freely naming skills. This avoids the model inventing skill
names that don't exist in your graph — a deliberate choice to keep
COVERS_CONCEPT edges valid by construction, not something you need to
validate after the fact.
"""

import json
import os

import ollama  # VERIFY: pip install ollama, current usage against its docs

MODEL_NAME = "llama3"  # VERIFY: run `ollama list`, use a model you actually have

EXTRACTION_PROMPT_TEMPLATE = """You are helping link an educational resource to the skills it covers.

Below is a list of VALID skill IDs and names — you may ONLY reference
skills from this list. Do not invent new skill names.

VALID SKILLS:
{skill_list}

RESOURCE TEXT:
{resource_text}

Identify which of the VALID SKILLS above this resource covers. Respond
with ONLY a JSON array, no other text, in this exact format:
[
  {{"skill_id": "exact id from the valid list", "relevance_score": 0.0-1.0, "evidence_snippet": "short quote from the resource text supporting this"}}
]

If the resource covers none of the valid skills, respond with an empty array: []
"""


def get_all_skills(tx):
    """Retrieves all existing skill IDs and names, for grounding the LLM prompt."""
    query = "MATCH (s:Skill) RETURN s.id AS id, s.name AS name"
    result = tx.run(query)
    return [dict(record) for record in result]


def format_skill_list(skills):
    return "\n".join(f"- {s['id']}: {s['name']}" for s in skills)


def call_llm_for_concept_extraction(resource_text: str, skills: list):
    skill_list_str = format_skill_list(skills)
    prompt = EXTRACTION_PROMPT_TEMPLATE.format(skill_list=skill_list_str, resource_text=resource_text)

    try:
        response = ollama.chat(
            model=MODEL_NAME,
            messages=[{"role": "user", "content": prompt}],
        )
        raw_content = response["message"]["content"]  # VERIFY: response shape against current ollama docs
        candidates = json.loads(raw_content)
    except Exception as e:
        print(f"WARNING: Ollama concept extraction failed or was unavailable ({e}). Falling back to simple heuristic matching.")
        candidates = _fallback_concept_extraction(resource_text, skills)

    # Extra safety: filter out any skill_id the model hallucinated despite
    # instructions, since grounding in the prompt doesn't GUARANTEE compliance.
    valid_ids = {s["id"] for s in skills}
    filtered = [c for c in candidates if c.get("skill_id") in valid_ids]

    if len(filtered) < len(candidates):
        print(f"WARNING: model proposed {len(candidates) - len(filtered)} skill_id(s) "
              f"not in the valid list — these were dropped, not silently kept.")

    return filtered


def _fallback_concept_extraction(resource_text: str, skills: list) -> list:
    """
    Heuristic matching fallback: checks if skill names appear in the resource text.
    """
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


def extract_and_link_concepts(tx, resource_id: str, resource_text: str):
    """
    Full flow: fetch valid skills, call LLM, filter hallucinations, link
    approved concepts to the resource.

    NOTE: unlike Phase 3's prerequisite extraction, this does NOT require
    a separate human-review step before merging in the current design —
    COVERS_CONCEPT is a lower-stakes relationship than PREREQUISITE_OF
    (it doesn't change graph structure/ordering, just tags content).
    If you want human review here too, that's a design addition to
    discuss with your teammate, not something already decided.
    """
    skills = get_all_skills(tx)
    concept_links = call_llm_for_concept_extraction(resource_text, skills)
    link_resource_to_concepts(tx, resource_id, concept_links)
    return concept_links
