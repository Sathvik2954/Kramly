# Student Knowledge Marketplace — Schema (Phase 5, Person A)

Proposed schema, not a verified industry standard — adjust as real usage informs it.

## Node: Resource
| Field | Type | Notes |
|---|---|---|
| id | string | Unique ID |
| title | string | |
| type | string | note / project / flashcard / interview_experience / research_summary |
| author_id | string | |
| upload_date | string (ISO) | |
| content_hash | string | SHA-256 hex digest, for exact-duplicate detection |
| storage_key | string | key used to retrieve content via StorageBackend |
| quality_score | float | nullable — set in Phase 6 by Person A's quality scoring |
| status | string | active / outdated |

## Node: Author
| Field | Type |
|---|---|
| id | string |
| name | string |

## Relationship: COVERS_CONCEPT
`(Resource)-[:COVERS_CONCEPT {relevance_score, evidence_snippet}]->(Skill)`
Created by concept_extraction.py — links a resource to the skill(s) it teaches.

## Relationship: AUTHORED_BY
`(Resource)-[:AUTHORED_BY]->(Author)`

## Relationship: SIMILAR_TO
`(Resource)-[:SIMILAR_TO {similarity_score}]->(Resource)`
NOT created by Person A's code — this is Person B's near-duplicate/embeddings work (Phase 5 split).

## Relationship: SUPERSEDES
`(Resource)-[:SUPERSEDES]->(Resource)`
NOT created in Phase 5 — this is Phase 6 (evolution tracking), Person A's track.

## Validation checklist
- [ ] content_hash correctly detects exact-duplicate uploads (test with identical bytes twice)
- [ ] COVERS_CONCEPT only links to skill IDs that actually exist in the graph (grounding — see concept_extraction.py comments)
- [ ] storage_key round-trips correctly (save then read returns identical bytes)
