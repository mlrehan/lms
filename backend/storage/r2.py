"""Cloudflare R2 storage (S3-compatible).

`boto3` is imported lazily and declared as an optional dependency, so a
deployment running on local storage -- the default -- does not carry the AWS
SDK it will never call. Selecting `STORAGE_MODE=r2` without it fails at
startup with a message naming the install command, rather than at the first
upload with an ImportError.

    pip install -e ".[r2]"
"""

from __future__ import annotations

import asyncio
from typing import Any, AsyncIterator

from backend.core.config import StorageSettings
from backend.core.errors import ConfigurationError, NotFoundError
from backend.storage.base import StorageBackend, StoredObject, assert_safe_key

_CHUNK = 64 * 1024


def _load_boto3() -> Any:
    try:
        import boto3  # noqa: PLC0415 - deliberately lazy, see module docstring
    except ImportError as exc:  # pragma: no cover - environment-dependent
        raise ConfigurationError(
            "STORAGE_MODE=r2 requires the boto3 package. Install it with: "
            'pip install -e ".[r2]"'
        ) from exc
    return boto3


class R2Storage(StorageBackend):
    def __init__(self, settings: StorageSettings) -> None:
        boto3 = _load_boto3()
        self._bucket = settings.r2_bucket
        self._expiry = settings.r2_presign_expiry_seconds
        self._client = boto3.client(
            "s3",
            endpoint_url=settings.r2_endpoint_url,
            aws_access_key_id=settings.r2_access_key_id,
            aws_secret_access_key=settings.r2_secret_access_key.get_secret_value(),
            # R2 ignores the region but the SDK insists on one being set.
            region_name="auto",
        )

    async def save(self, key: str, data: bytes, *, content_type: str | None) -> StoredObject:
        assert_safe_key(key)
        kwargs: dict[str, Any] = {"Bucket": self._bucket, "Key": key, "Body": data}
        if content_type:
            kwargs["ContentType"] = content_type
        # boto3 is synchronous; without the thread hop every upload would
        # block the event loop for the duration of the network round trip.
        await asyncio.to_thread(self._client.put_object, **kwargs)
        return StoredObject(key=key, size=len(data), mime_type=content_type)

    async def open_stream(self, key: str) -> AsyncIterator[bytes]:
        assert_safe_key(key)
        try:
            response = await asyncio.to_thread(
                self._client.get_object, Bucket=self._bucket, Key=key
            )
        except Exception as exc:  # noqa: BLE001 - botocore's error types are lazy-built
            raise NotFoundError("File not found.") from exc

        body = response["Body"]

        async def _iter() -> AsyncIterator[bytes]:
            try:
                while chunk := await asyncio.to_thread(body.read, _CHUNK):
                    yield chunk
            finally:
                await asyncio.to_thread(body.close)

        return _iter()

    async def open_range(self, key: str, start: int, end: int) -> AsyncIterator[bytes]:
        assert_safe_key(key)
        try:
            response = await asyncio.to_thread(
                self._client.get_object,
                Bucket=self._bucket,
                Key=key,
                # S3 speaks the same inclusive-end convention as HTTP, so the
                # range is passed through rather than translated -- a
                # translation is one off-by-one away from a truncated video.
                Range=f"bytes={start}-{end}",
            )
        except Exception as exc:  # noqa: BLE001 - botocore's error types are lazy-built
            raise NotFoundError("File not found.") from exc

        body = response["Body"]

        async def _iter() -> AsyncIterator[bytes]:
            try:
                while chunk := await asyncio.to_thread(body.read, _CHUNK):
                    yield chunk
            finally:
                await asyncio.to_thread(body.close)

        return _iter()

    async def size(self, key: str) -> int:
        assert_safe_key(key)
        try:
            head = await asyncio.to_thread(
                self._client.head_object, Bucket=self._bucket, Key=key
            )
        except Exception as exc:  # noqa: BLE001
            raise NotFoundError("File not found.") from exc
        return int(head["ContentLength"])

    async def delete(self, key: str) -> None:
        assert_safe_key(key)
        await asyncio.to_thread(
            self._client.delete_object, Bucket=self._bucket, Key=key
        )

    async def exists(self, key: str) -> bool:
        assert_safe_key(key)
        try:
            await asyncio.to_thread(
                self._client.head_object, Bucket=self._bucket, Key=key
            )
        except Exception:  # noqa: BLE001
            return False
        return True

    def presigned_url(self, key: str) -> str | None:
        """A short-lived direct download URL, so file traffic bypasses this
        server entirely. Authorisation still happens here first -- the URL is
        only minted once the caller has been checked."""
        assert_safe_key(key)
        return self._client.generate_presigned_url(
            "get_object",
            Params={"Bucket": self._bucket, "Key": key},
            ExpiresIn=self._expiry,
        )
