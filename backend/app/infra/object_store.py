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
    - OBJECT_STORE_ENDPOINT: S3/MinIO endpoint URL.
    - OBJECT_STORE_BUCKET: bucket name.
    - MINIO_ROOT_USER: access key.
    - MINIO_ROOT_PASSWORD: secret key.
    """
    from app.infra.object_store_s3 import S3ObjectStore

    endpoint_url = os.environ["OBJECT_STORE_ENDPOINT"]
    bucket = os.environ["OBJECT_STORE_BUCKET"]
    access_key = os.environ["MINIO_ROOT_USER"]
    secret_key = os.environ["MINIO_ROOT_PASSWORD"]

    return S3ObjectStore(
        endpoint_url=endpoint_url,
        bucket=bucket,
        access_key=access_key,
        secret_key=secret_key,
    )
