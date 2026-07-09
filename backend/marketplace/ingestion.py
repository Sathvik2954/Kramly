"""
ingestion.py
Phase 5, Person A — ingestion pipeline: accept content, hash it, save via
storage backend, create a Resource node, check for exact duplicates.

Does NOT do near-duplicate/embedding-based detection — that's Person B's
Phase 5 track. This file only handles exact-hash duplicate checking.

VERIFY BEFORE RUNNING: Neo4j driver call shapes (tx.run, MERGE) checked
against the same 6.2 docs used elsewhere in this project — re-verify if
your driver version differs.
"""

import hashlib
import uuid
from datetime import datetime, timezone

from marketplace.storage import get_storage_backend


def compute_content_hash(content: bytes) -> str:
    """
    SHA-256 hex digest of the raw content — standard, well-established
    hashing, not something I'm uncertain about (unlike the driver/LLM
    API calls elsewhere).
    """
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
    enforced here — add that check yourself if you want strict validation,
    since I didn't want to silently reject a type you may want to add later.
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
