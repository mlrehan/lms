"""Backend selection, driven entirely by `STORAGE_MODE`."""

from __future__ import annotations

from functools import lru_cache

from backend.core.config import StorageMode, get_settings
from backend.core.errors import ConfigurationError
from backend.storage.base import StorageBackend


@lru_cache(maxsize=1)
def get_storage() -> StorageBackend:
    """The process-wide storage backend.

    Cached because both implementations are stateless request-to-request and
    the R2 client holds a connection pool worth reusing -- building one per
    upload would open a fresh TLS connection every time.
    """
    settings = get_settings().storage

    if settings.mode is StorageMode.LOCAL:
        from backend.storage.local import LocalStorage

        return LocalStorage(settings.local_path)

    if settings.mode is StorageMode.R2:
        from backend.storage.r2 import R2Storage

        return R2Storage(settings)

    raise ConfigurationError(f"Unsupported STORAGE_MODE: {settings.mode!r}")
