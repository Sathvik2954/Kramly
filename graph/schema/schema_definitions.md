# Skill Dependency Graph — Schema

Proposed schema, not a verified industry standard — adjust as your real data needs evolve.

## Node: Skill
| Field | Type | Notes |
|---|---|---|
| id | string | Unique ID, e.g. `py01` |
| name | string | Human-readable skill name |
| domain | string | e.g. "PythonDS", "WebDev" |
| difficulty_level | string | beginner / intermediate / advanced |

## Relationship: PREREQUISITE_OF
Direction: `(prerequisite_skill)-[:PREREQUISITE_OF]->(dependent_skill)`

| Field | Type | Notes |
|---|---|---|
| strength | string | "strict" (mandatory) or "soft" (helpful, not required) |
| source | string | "manual" (hand-authored) or "extracted" (LLM-proposed via graph/extraction/pipeline.py) |

## Node: Learner
| Field | Type | Notes |
|---|---|---|
| id | string | |
| known_skills | list | with confidence/decay metadata |
| target_skill | string | |
| deadline | date | optional |

## Validation checklist
- [ ] No cycles in PREREQUISITE_OF edges (run `check_for_cycles` in load_all_domains.py)
- [ ] Every `from_skill_id`/`to_skill_id` in prerequisites.csv exists in skills.csv
- [ ] Manually inspected in Neo4j Browser: `MATCH (s:Skill)-[r:PREREQUISITE_OF]->(t:Skill) RETURN s, r, t`
