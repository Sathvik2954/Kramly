"""
base.py
Phase 5, Person A — Storage abstraction interface (local now, cloud-ready later).
See Phase4-8_Marketplace_Development_Plan.md for the full rationale.
"""

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
