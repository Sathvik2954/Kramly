"""
cloud_stub.py
Phase 5, Person A — placeholder for future cloud storage migration.

NOT IMPLEMENTED, intentionally. When you actually migrate, implement this
using your cloud provider's current SDK (e.g. boto3 for S3) — I'm not
writing real boto3 calls now, since code written against an API you
aren't using yet risks being stale by the time you need it. Check the
SDK's current docs at that point instead.
"""

from .base import StorageBackend


class CloudFileStorage(StorageBackend):
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
