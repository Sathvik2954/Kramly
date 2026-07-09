"""
test_marketplace_storage.py
Phase 5, Person A — tests for the storage abstraction (LocalFileStorage).
Uses pytest's tmp_path fixture for a real, isolated filesystem location —
no mocking needed here since it's genuinely testing file I/O.
"""

from marketplace.storage.local import LocalFileStorage


def test_save_and_read_roundtrip(tmp_path):
    storage = LocalFileStorage(base_dir=str(tmp_path))
    content = b"hello world"
    storage.save("test_key", content)
    result = storage.read("test_key")
    assert result == content


def test_exists_true_after_save(tmp_path):
    storage = LocalFileStorage(base_dir=str(tmp_path))
    storage.save("some/nested/key", b"data")
    assert storage.exists("some/nested/key") is True


def test_exists_false_before_save(tmp_path):
    storage = LocalFileStorage(base_dir=str(tmp_path))
    assert storage.exists("never_saved") is False


def test_delete_removes_file(tmp_path):
    storage = LocalFileStorage(base_dir=str(tmp_path))
    storage.save("to_delete", b"data")
    assert storage.exists("to_delete") is True
    storage.delete("to_delete")
    assert storage.exists("to_delete") is False


def test_delete_nonexistent_key_does_not_raise(tmp_path):
    storage = LocalFileStorage(base_dir=str(tmp_path))
    storage.delete("never_existed")  # should not raise
