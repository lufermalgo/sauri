"""S3-compatible implementation of ObjectStore (local MinIO / S3 / GCS)."""

from __future__ import annotations

import asyncio
import functools
import time
from contextlib import suppress
from typing import Any

import boto3
from botocore.config import Config

from app.infra.object_store import ObjectStore


class S3ObjectStore(ObjectStore):
    """Object store backed by an S3-compatible endpoint.

    Works with MinIO (local development), AWS S3, and GCS (S3 interop).
    The (synchronous) boto3 operations run on a separate thread so they
    don't block the asyncio event loop.
    """

    def __init__(
        self,
        endpoint_url: str,
        bucket: str,
        access_key: str,
        secret_key: str,
        presign_endpoint_url: str | None = None,
    ) -> None:
        self._bucket = bucket
        client_options = {
            "aws_access_key_id": access_key,
            "aws_secret_access_key": secret_key,
            "config": Config(signature_version="s3v4"),
        }
        self._client = boto3.client(
            "s3", endpoint_url=endpoint_url, **client_options
        )
        self._presign_client = (
            boto3.client("s3", endpoint_url=presign_endpoint_url, **client_options)
            if presign_endpoint_url and presign_endpoint_url != endpoint_url
            else self._client
        )

    # ------------------------------------------------------------------
    # ObjectStore interface
    # ------------------------------------------------------------------

    async def save(
        self,
        key: str,
        content: bytes,
        content_type: str = "application/octet-stream",
    ) -> str:
        """Uploads an object to the bucket and returns the key as reference."""
        await asyncio.to_thread(
            functools.partial(
                self._client.put_object,
                Bucket=self._bucket,
                Key=key,
                Body=content,
                ContentType=content_type,
            )
        )
        return key

    async def get(self, reference: str) -> bytes:
        """Downloads the content of an object from the bucket."""
        response = await asyncio.to_thread(
            functools.partial(
                self._client.get_object,
                Bucket=self._bucket,
                Key=reference,
            )
        )
        body: bytes = response["Body"].read()
        return body

    async def get_bounded(
        self,
        reference: str,
        max_bytes: int,
        deadline_monotonic: float,
    ) -> bytes:
        """Fetch an object only when its declared and actual sizes fit the cap."""
        if max_bytes < 0 or deadline_monotonic <= time.monotonic():
            raise ValueError("bounded object read unavailable")
        body: Any = None
        try:
            remaining = deadline_monotonic - time.monotonic()
            async with asyncio.timeout(remaining):
                response: dict[str, Any] = await asyncio.to_thread(
                    functools.partial(
                        self._client.get_object,
                        Bucket=self._bucket,
                        Key=reference,
                    )
                )
            content_length = response.get("ContentLength")
            body = response.get("Body")
            if (
                not isinstance(content_length, int)
                or isinstance(content_length, bool)
                or content_length < 0
                or content_length > max_bytes
                or body is None
            ):
                raise ValueError("bounded object read unavailable")

            chunks: list[bytes] = []
            total = 0
            while total < max_bytes + 1:
                remaining = deadline_monotonic - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError("bounded object read deadline expired")
                size = max_bytes + 1 - total
                async with asyncio.timeout(remaining):
                    chunk = await asyncio.to_thread(body.read, size)
                if not isinstance(chunk, bytes):
                    raise ValueError("bounded object read unavailable")
                if not chunk:
                    break
                chunks.append(chunk)
                total += len(chunk)
                if total > max_bytes:
                    raise ValueError("bounded object read unavailable")
            if total != content_length:
                raise ValueError("bounded object read unavailable")
            return b"".join(chunks)
        except TimeoutError:
            raise
        except Exception as error:
            raise OSError("bounded object read unavailable") from error
        finally:
            if body is not None:
                with suppress(Exception):
                    await asyncio.to_thread(body.close)

    async def delete(self, reference: str) -> None:
        """Deletes an object from the bucket."""
        await asyncio.to_thread(
            functools.partial(
                self._client.delete_object,
                Bucket=self._bucket,
                Key=reference,
            )
        )

    async def temporary_read_url(
        self,
        reference: str,
        ttl_seconds: int = 3600,
    ) -> str:
        """Generates a pre-signed read URL with expiration."""
        url: str = await asyncio.to_thread(
            functools.partial(
                self._presign_client.generate_presigned_url,
                ClientMethod="get_object",
                Params={"Bucket": self._bucket, "Key": reference},
                ExpiresIn=ttl_seconds,
            )
        )
        return url
