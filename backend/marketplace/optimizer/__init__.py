"""
__init__.py
Phase 5, Person A — single configuration point for storage backend choice.
Rest of the app calls get_storage_backend() and never imports
LocalFileStorage/CloudFileStorage directly — migrating later means
changing ONE line here, not every call site.
"""

import os
from .local import LocalFileStorage
# from .cloud_stub import CloudFileStorage  # uncomment once implemented


def get_storage_backend():
    backend = os.environ.get("STORAGE_BACKEND", "local")
    if backend == "local":
        return LocalFileStorage(base_dir=os.environ.get("LOCAL_STORAGE_DIR", "./marketplace_files"))
    elif backend == "cloud":
        raise NotImplementedError("Implement CloudFileStorage before setting STORAGE_BACKEND=cloud")
    else:
        raise ValueError(f"Unknown STORAGE_BACKEND: {backend}")
