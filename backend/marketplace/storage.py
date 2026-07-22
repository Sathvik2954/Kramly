"""
storage.py
Storage abstraction (local now, cloud-ready later).

Consolidated from the former storage/ package (base.py + local.py +
cloud_stub.py + __init__.py) — four small files for one interface plus
two implementations. The rest of the app calls get_storage_backend() and
never imports LocalFileStorage/CloudFileStorage directly — migrating to
cloud storage later means changing ONE constant here, not every call site.

SECURITY NOTE (flagged, not fixed here): `key` is used directly in a path
join by LocalFileStorage. If `key` ever comes from raw user input without
sanitization upstream, this is a directory-traversal risk (e.g.
key="../../etc/passwd"). ingestion.py generates keys internally
(content-hash-based), which avoids this in the current design — but if
you later accept user-supplied keys anywhere, sanitize them first.
"""

import os
from abc import ABC, abstractmethod


class StorageBackend(ABC):
    @abstractmethod
    def save(self, key: str, content: bytes) -> str:
        """Saves content under `key`, returns a retrievable reference (path or URL)."""
        ...

    @abstractmethod
    def read(self, key: str) -> bytes:
        """Retrieves content by key."""
        ...

    @abstractmethod
    def delete(self, key: str) -> None:
        ...

    @abstractmethod
    def exists(self, key: str) -> bool:
        ...


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


class CloudFileStorage(StorageBackend):
    """NOT IMPLEMENTED, intentionally. When you actually migrate, implement
    this using your cloud provider's current SDK (e.g. boto3 for S3) —
    code written against an API you aren't using yet risks being stale by
    the time you need it. Check the SDK's current docs at that point.
    """

    def __init__(self, bucket_name: str):
        raise NotImplementedError(
            "Implement this when migrating to cloud storage, using your "
            "provider's current SDK docs at that time."
        )

    def save(self, key: str, content: bytes) -> str:
        raise NotImplementedError

    def read(self, key: str) -> bytes:
        raise NotImplementedError

    def delete(self, key: str) -> None:
        raise NotImplementedError

    def exists(self, key: str) -> bool:
        raise NotImplementedError


def get_storage_backend() -> StorageBackend:
    """Backend selection and local dir now come from Settings.storage_backend /
    Settings.local_storage_dir (app/config.py) instead of raw os.environ.get()
    calls, so they're validated/typed alongside every other tunable constant."""
    from app.config import settings

    backend = settings.storage_backend
    if backend == "local":
        return LocalFileStorage(base_dir=settings.local_storage_dir)
    elif backend == "cloud":
        raise NotImplementedError("Implement CloudFileStorage before setting STORAGE_BACKEND=cloud")
    else:
        raise ValueError(f"Unknown STORAGE_BACKEND: {backend}")
