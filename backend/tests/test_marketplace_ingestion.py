"""
test_marketplace_ingestion.py
Phase 5, Person A — tests for ingestion.py.

NOTE: uses hand-written mocks (FakeTx) rather than your real conftest.py
fixtures — adapt to your actual mocking pattern before merging, same
caveat as test_decay_scanner.py.

Only tests the deterministic parts (hashing, duplicate detection logic).
Does NOT test storage.save()/read() against a real filesystem here —
that's covered separately in test_marketplace_storage.py.
"""

import pytest
from marketplace.ingestion import compute_content_hash, check_exact_duplicate, ingest_resource


class FakeRecord(dict):
    pass


class FakeResult:
    def __init__(self, records):
        self._records = records

    def __iter__(self):
        return iter(self._records)


class FakeTx:
    """Mock transaction. `existing_resources` simulates what's already in Neo4j."""
    def __init__(self, existing_resources=None):
        self.existing_resources = existing_resources or []
        self.last_query = None
        self.last_params = None

    def run(self, query, **params):
        self.last_query = query
        self.last_params = params
        if "content_hash:" in query.replace(" ", "") or "content_hash: $content_hash" in query:
            matches = [r for r in self.existing_resources if r["content_hash"] == params.get("content_hash")]
            return FakeResult([FakeRecord(m) for m in matches])
        # For the MERGE/create query, just record the call — nothing to return
        return FakeResult([])


def test_compute_content_hash_is_deterministic():
    content = b"some resource content"
    h1 = compute_content_hash(content)
    h2 = compute_content_hash(content)
    assert h1 == h2


def test_compute_content_hash_differs_for_different_content():
    h1 = compute_content_hash(b"content A")
    h2 = compute_content_hash(b"content B")
    assert h1 != h2


def test_check_exact_duplicate_finds_match():
    content_hash = compute_content_hash(b"duplicate content")
    tx = FakeTx(existing_resources=[
        {"id": "res_001", "title": "Existing Note", "upload_date": "2026-01-01T00:00:00+00:00",
         "content_hash": content_hash},
    ])
    matches = check_exact_duplicate(tx, content_hash)
    assert len(matches) == 1
    assert matches[0]["id"] == "res_001"


def test_check_exact_duplicate_no_match():
    tx = FakeTx(existing_resources=[])
    matches = check_exact_duplicate(tx, "some_hash_that_does_not_exist")
    assert matches == []


def test_ingest_resource_raises_on_duplicate_by_default(monkeypatch, tmp_path):
    """
    VERIFY: this test patches get_storage_backend to use a temp dir rather
    than your real STORAGE_BACKEND env var setup — adjust if your project's
    conftest.py already handles this differently.
    """
    import marketplace.ingestion as ingestion_module
    from marketplace.storage.local import LocalFileStorage

    monkeypatch.setattr(
        ingestion_module, "get_storage_backend",
        lambda: LocalFileStorage(base_dir=str(tmp_path))
    )

    content = b"some duplicate content"
    content_hash = compute_content_hash(content)
    tx = FakeTx(existing_resources=[
        {"id": "res_existing", "title": "Old Note", "upload_date": "2026-01-01T00:00:00+00:00",
         "content_hash": content_hash},
    ])

    with pytest.raises(ValueError):
        ingest_resource(tx, title="New Note", resource_type="note",
                         author_id="author_001", content=content)


def test_ingest_resource_allows_duplicate_when_flagged(monkeypatch, tmp_path):
    import marketplace.ingestion as ingestion_module
    from marketplace.storage.local import LocalFileStorage

    monkeypatch.setattr(
        ingestion_module, "get_storage_backend",
        lambda: LocalFileStorage(base_dir=str(tmp_path))
    )

    content = b"some duplicate content"
    content_hash = compute_content_hash(content)
    tx = FakeTx(existing_resources=[
        {"id": "res_existing", "title": "Old Note", "upload_date": "2026-01-01T00:00:00+00:00",
         "content_hash": content_hash},
    ])

    result = ingest_resource(tx, title="New Note", resource_type="note",
                              author_id="author_001", content=content,
                              allow_duplicate=True)
    assert result["content_hash"] == content_hash
