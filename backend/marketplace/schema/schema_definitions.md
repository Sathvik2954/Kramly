# Student Knowledge Marketplace — Schema

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
| quality_score | float | nullable — set by quality.py's scoring pass |
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
Created by the near-duplicate/embeddings work in discovery.py, not ingestion.py.

## Relationship: SUPERSEDES
`(Resource)-[:SUPERSEDES]->(Resource)`
Created by the evolution-tracking logic in quality.py, not ingestion.py.

## Validation checklist
- [ ] content_hash correctly detects exact-duplicate uploads (test with identical bytes twice)
- [ ] COVERS_CONCEPT only links to skill IDs that actually exist in the graph (grounding — see concept_extraction.py comments)
- [ ] storage_key round-trips correctly (save then read returns identical bytes)
