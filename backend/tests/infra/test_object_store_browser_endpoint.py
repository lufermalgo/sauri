from __future__ import annotations

from typing import Any

import boto3
import pytest

from app.infra import object_store, object_store_s3


class _PresigningClient:
    def __init__(self, endpoint_url: str) -> None:
        self.endpoint_url = endpoint_url
        self.call: dict[str, Any] | None = None
        self.storage_call: dict[str, Any] | None = None

    def generate_presigned_url(self, **kwargs: Any) -> str:
        self.call = kwargs
        return f"{self.endpoint_url}/sauri-recordings/synthetic/audio.webm?signature=synthetic"

    def put_object(self, **kwargs: Any) -> None:
        self.storage_call = kwargs


async def test_s3_store_signs_with_browser_endpoint_without_changing_storage_endpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clients: list[_PresigningClient] = []

    def client(service_name: str, **kwargs: Any) -> _PresigningClient:
        assert service_name == "s3"
        result = _PresigningClient(kwargs["endpoint_url"])
        clients.append(result)
        return result

    monkeypatch.setattr(boto3, "client", client)
    store = object_store_s3.S3ObjectStore(
        endpoint_url="http://minio:9000",
        presign_endpoint_url="http://localhost:9000",
        bucket="sauri-recordings",
        access_key="synthetic-user",
        secret_key="synthetic-password",
    )

    assert len(clients) == 2
    assert clients[0].endpoint_url == "http://minio:9000"
    assert clients[1].endpoint_url == "http://localhost:9000"

    await store.save("synthetic/audio.webm", b"synthetic")
    signed_url = await store.temporary_read_url("synthetic/audio.webm", ttl_seconds=120)

    assert clients[0].storage_call == {
        "Bucket": "sauri-recordings",
        "Key": "synthetic/audio.webm",
        "Body": b"synthetic",
        "ContentType": "application/octet-stream",
    }
    assert signed_url.startswith("http://localhost:9000/")
    assert clients[1].call == {
        "ClientMethod": "get_object",
        "Params": {"Bucket": "sauri-recordings", "Key": "synthetic/audio.webm"},
        "ExpiresIn": 120,
    }


def test_object_store_factory_reads_optional_browser_endpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    class _ConfiguredStore:
        def __init__(self, **kwargs: Any) -> None:
            captured.update(kwargs)

    monkeypatch.setattr(object_store_s3, "S3ObjectStore", _ConfiguredStore)
    monkeypatch.setenv("OBJECT_STORE_ENDPOINT", "http://minio:9000")
    monkeypatch.setenv("OBJECT_STORE_PUBLIC_ENDPOINT", "http://localhost:9000")
    monkeypatch.setenv("OBJECT_STORE_BUCKET", "sauri-recordings")
    monkeypatch.setenv("MINIO_ROOT_USER", "synthetic-user")
    monkeypatch.setenv("MINIO_ROOT_PASSWORD", "synthetic-password")

    object_store.create_object_store()

    assert captured["endpoint_url"] == "http://minio:9000"
    assert captured["presign_endpoint_url"] == "http://localhost:9000"
