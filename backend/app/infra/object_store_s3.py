"""S3-compatible implementation of ObjectStore (local MinIO / S3 / GCS)."""

from __future__ import annotations

import asyncio
import functools
import re
import time
import unicodedata
from contextlib import suppress
from typing import Any, BinaryIO
from urllib.parse import quote

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from app.infra.object_store import ObjectAvailability, ObjectStore


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

    async def save_stream(
        self,
        key: str,
        content: BinaryIO,
        content_type: str = "application/octet-stream",
    ) -> str:
        """Uploads a spooled file in one PUT, reading it in chunks instead of loading it."""
        content.seek(0)
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

    async def inspect(self, reference: str) -> ObjectAvailability:
        """Only an explicit NoSuchKey is evidence of an absent object.

        S3 HEAD can return an unqualified 404 for an inaccessible/missing bucket;
        neither that nor a network, permission or service error proves key absence.
        """
        try:
            await asyncio.to_thread(
                functools.partial(self._client.head_object, Bucket=self._bucket, Key=reference)
            )
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code")
            status = exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
            if status != 404 or code not in {"NoSuchKey", "404"}:
                raise
            # A bare HEAD 404 is ambiguous. Verify the bucket is accessible,
            # then request metadata for this exact key (never download bytes).
            # S3-compatible HEAD often erases the structured NoSuchKey code;
            # GetObjectAttributes returns it, including on RustFS.
            await asyncio.to_thread(
                functools.partial(self._client.head_bucket, Bucket=self._bucket)
            )
            if code == "NoSuchKey":
                return "missing"
            try:
                await asyncio.to_thread(functools.partial(
                    self._client.get_object_attributes, Bucket=self._bucket,
                    Key=reference, ObjectAttributes=["ObjectSize"],
                ))
            except ClientError as attributes_exc:
                if (attributes_exc.response.get("Error", {}).get("Code") == "NoSuchKey"
                        and attributes_exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode") == 404):
                    return "missing"
                raise
            raise ValueError("conflicting S3 object metadata response") from exc
        return "available"

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

    async def _close_body(self, body: Any) -> None:
        close_task = asyncio.create_task(asyncio.to_thread(body.close))
        try:
            await asyncio.shield(close_task)
        except asyncio.CancelledError:
            await self._await_thread_after_cancel(close_task)
            raise

    @staticmethod
    async def _await_thread_after_cancel(task: asyncio.Task[Any]) -> Any | None:
        """Keep an executor worker supervised through cancellation and reap."""
        while not task.done():
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError:
                continue
            except Exception:
                return None
        if task.cancelled():
            return None
        with suppress(BaseException):
            return task.result()
        return None

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
            response_task = asyncio.create_task(
                asyncio.to_thread(
                    functools.partial(
                        self._client.get_object,
                        Bucket=self._bucket,
                        Key=reference,
                    )
                )
            )
            remaining = deadline_monotonic - time.monotonic()
            try:
                async with asyncio.timeout(remaining):
                    response: dict[str, Any] = await asyncio.shield(response_task)
            except (TimeoutError, asyncio.CancelledError) as error:
                late_response = await self._await_thread_after_cancel(response_task)
                if late_response is not None:
                    late_body = late_response.get("Body")
                    if late_body is not None:
                        with suppress(Exception):
                            await self._close_body(late_body)
                raise error
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
                read_task = asyncio.create_task(asyncio.to_thread(body.read, size))
                try:
                    async with asyncio.timeout(remaining):
                        chunk = await asyncio.shield(read_task)
                except (TimeoutError, asyncio.CancelledError) as error:
                    with suppress(Exception):
                        await self._close_body(body)
                    await self._await_thread_after_cancel(read_task)
                    raise error
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
                    await self._close_body(body)

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

    async def temporary_download_url(
        self,
        reference: str,
        filename: str,
        ttl_seconds: int = 300,
    ) -> str:
        """Pre-signed read URL whose response carries ``Content-Disposition: attachment``."""
        url: str = await asyncio.to_thread(
            functools.partial(
                self._presign_client.generate_presigned_url,
                ClientMethod="get_object",
                Params={
                    "Bucket": self._bucket,
                    "Key": reference,
                    "ResponseContentDisposition": attachment_content_disposition(filename),
                },
                ExpiresIn=ttl_seconds,
            )
        )
        return url


def attachment_content_disposition(filename: str) -> str:
    """``attachment`` header with an ASCII fallback and the exact name as RFC 5987 ``filename*``."""
    fallback = unicodedata.normalize("NFKD", filename).encode("ascii", "ignore").decode("ascii")
    fallback = re.sub(r'[^A-Za-z0-9 ._()\[\]+@&#~-]', "_", fallback).strip() or "download"
    return f"attachment; filename=\"{fallback}\"; filename*=UTF-8''{quote(filename, safe='')}"
