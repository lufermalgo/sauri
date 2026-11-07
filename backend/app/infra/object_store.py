"""Abstract ObjectStore interface and creation factory."""

from __future__ import annotations

import os
from abc import ABC, abstractmethod


class ObjectStore(ABC):
    """Cloud-agnostic abstraction for object storage.

    Contract:
    - save: persists an object and returns the reference key.
    - get: retrieves the content of an object by reference.
    - delete: deletes an object by reference.
    - temporary_read_url: generates a pre-signed read URL with a TTL.
    """

    @abstractmethod
    async def save(
        self,
        key: str,
        content: bytes,
        content_type: str = "application/octet-stream",
    ) -> str:
        """Stores an object and returns the reference key."""
        ...

    @abstractmethod
    async def get(self, reference: str) -> bytes:
        """Retrieves the content of a stored object."""
        ...

    async def get_bounded(
        self,
        reference: str,
        max_bytes: int,
        deadline_monotonic: float,
    ) -> bytes:
        """Read at most ``max_bytes`` plus one rejection sentinel byte.

        Stores that cannot enforce a bounded read must fail closed; callers must
        never fall back to :meth:`get` for security-sensitive bounded media.
        """
        raise NotImplementedError("bounded reads are not supported by this object store")

    @abstractmethod
    async def delete(self, reference: str) -> None:
        """Deletes an object from the store."""
        ...

    @abstractmethod
    async def temporary_read_url(
        self,
        reference: str,
        ttl_seconds: int = 3600,
    ) -> str:
        """Generates a temporary pre-signed URL for reading the object."""
        ...


def create_object_store() -> ObjectStore:
    """Factory that creates the configured ObjectStore implementation.

    Reads the environment variables:
    - OBJECT_STORE_ENDPOINT: internal S3/MinIO endpoint URL used by backend I/O.
    - OBJECT_STORE_PUBLIC_ENDPOINT: optional browser-reachable endpoint used only in signatures.
    - OBJECT_STORE_BUCKET: bucket name.
    - MINIO_ROOT_USER: access key.
    - MINIO_ROOT_PASSWORD: secret key.
    """
    from app.infra.object_store_s3 import S3ObjectStore

    endpoint_url = os.environ["OBJECT_STORE_ENDPOINT"]
    public_endpoint_url = os.environ.get("OBJECT_STORE_PUBLIC_ENDPOINT")
    bucket = os.environ["OBJECT_STORE_BUCKET"]
    access_key = os.environ["MINIO_ROOT_USER"]
    secret_key = os.environ["MINIO_ROOT_PASSWORD"]

    return S3ObjectStore(
        endpoint_url=endpoint_url,
        presign_endpoint_url=public_endpoint_url,
        bucket=bucket,
        access_key=access_key,
        secret_key=secret_key,
    )
