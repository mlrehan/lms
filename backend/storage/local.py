"""Local filesystem storage -- the default backend."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import AsyncIterator

from backend.core.errors import NotFoundError
from backend.storage.base import StorageBackend, StoredObject, assert_safe_key

_CHUNK = 64 * 1024


class LocalStorage(StorageBackend):
    def __init__(self, root: Path) -> None:
        self._root = Path(root).resolve()
        self._root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        assert_safe_key(key)
        resolved = (self._root / key).resolve()
        # Second line of defence behind `assert_safe_key`: even if a key
        # slipped through the pattern check, a resolved path outside the
        # storage root is refused. Symlinks are what make this worth doing
        # twice -- a symlinked directory inside the root can point anywhere,
        # and only resolution afterwards reveals it.
        if not resolved.is_relative_to(self._root):
            raise NotFoundError("File not found.")
        return resolved

    async def save(self, key: str, data: bytes, *, content_type: str | None) -> StoredObject:
        path = self._path(key)

        def _write() -> int:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
            return path.stat().st_size

        # Blocking file IO moved off the event loop; a large upload written
        # inline would stall every other request on this worker.
        size = await asyncio.to_thread(_write)
        return StoredObject(key=key, size=size, mime_type=content_type)

    async def open_stream(self, key: str) -> AsyncIterator[bytes]:
        path = self._path(key)
        if not path.is_file():
            raise NotFoundError("File not found.")

        async def _iter() -> AsyncIterator[bytes]:
            with path.open("rb") as handle:
                while chunk := await asyncio.to_thread(handle.read, _CHUNK):
                    yield chunk

        return _iter()

    async def open_range(self, key: str, start: int, end: int) -> AsyncIterator[bytes]:
        path = self._path(key)
        if not path.is_file():
            raise NotFoundError("File not found.")

        async def _iter() -> AsyncIterator[bytes]:
            remaining = end - start + 1
            with path.open("rb") as handle:
                await asyncio.to_thread(handle.seek, start)
                while remaining > 0:
                    chunk = await asyncio.to_thread(handle.read, min(_CHUNK, remaining))
                    if not chunk:
                        break
                    remaining -= len(chunk)
                    yield chunk

        return _iter()

    async def size(self, key: str) -> int:
        path = self._path(key)
        if not path.is_file():
            raise NotFoundError("File not found.")
        return (await asyncio.to_thread(path.stat)).st_size

    async def delete(self, key: str) -> None:
        path = self._path(key)
        # Missing is success: delete is called during cleanup paths where a
        # partially-written or already-removed file must not turn into an
        # error the caller has no way to act on.
        await asyncio.to_thread(path.unlink, True)

    async def exists(self, key: str) -> bool:
        return await asyncio.to_thread(self._path(key).is_file)

    def presigned_url(self, key: str) -> str | None:
        """Local files have no direct URL -- the API streams them, so the
        permission check cannot be bypassed by holding a link."""
        return None
