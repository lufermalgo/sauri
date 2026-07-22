"""S3-compatible implementation of ObjectStore (local MinIO / S3 / GCS)."""

from __future__ import annotations

import asyncio
import functools

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
    ) -> None:
        self._bucket = bucket
        self._client = boto3.client(
            "s3",
            endpoint_url=endpoint_url,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            config=Config(signature_version="s3v4"),
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
                self._client.generate_presigned_url,
                ClientMethod="get_object",
                Params={"Bucket": self._bucket, "Key": reference},
                ExpiresIn=ttl_seconds,
            )
        )
        return url
