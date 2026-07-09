"""
local.py
Phase 5, Person A — Local filesystem storage implementation.

SECURITY NOTE (flagged, not fixed here): `key` is used directly in a path
join. If `key` ever comes from raw user input without sanitization
upstream, this is a directory-traversal risk (e.g. key="../../etc/passwd").
Ingestion.py generates keys internally (content-hash-based), which avoids
this in the current design — but if you later accept user-supplied keys
anywhere, sanitize them before calling save()/read()/delete().
"""

import os
from .base import StorageBackend


class LocalFileStorage(StorageBackend):
    def __init__(self, base_dir: str):
        self.base_dir = base_dir
        os.makedirs(base_dir, exist_ok=True)

    def _full_path(self, key: str) -> str:
        return os.path.join(self.base_dir, key)

    def save(self, key: str, content: bytes) -> str:
        path = self._full_path(key)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(content)
        return path

    def read(self, key: str) -> bytes:
        with open(self._full_path(key), "rb") as f:
            return f.read()

    def delete(self, key: str) -> None:
        path = self._full_path(key)
        if os.path.exists(path):
            os.remove(path)

    def exists(self, key: str) -> bool:
        return os.path.exists(self._full_path(key))
