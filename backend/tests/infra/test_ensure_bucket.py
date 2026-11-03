from unittest.mock import Mock, patch

import pytest
from botocore.exceptions import ClientError

from app.infra.ensure_bucket import ensure_bucket


def _client_error(code: str) -> ClientError:
    return ClientError({"Error": {"Code": code}}, "HeadBucket")


def test_bucket_creation_is_idempotent(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OBJECT_STORE_ENDPOINT", "http://object-store.test")
    monkeypatch.setenv("OBJECT_STORE_BUCKET", "synthetic-recordings")
    monkeypatch.setenv("MINIO_ROOT_USER", "synthetic-user")
    monkeypatch.setenv("MINIO_ROOT_PASSWORD", "synthetic-password")

    client = Mock()
    client.head_bucket.side_effect = [_client_error("404"), {"ResponseMetadata": {}}, {"ResponseMetadata": {}}]
    with patch("app.infra.ensure_bucket.boto3.client", return_value=client):
        ensure_bucket()
        ensure_bucket()

    client.create_bucket.assert_called_once_with(Bucket="synthetic-recordings")
    assert client.head_bucket.call_count == 2


def test_bucket_permission_failure_is_not_reported_as_ready(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OBJECT_STORE_ENDPOINT", "http://object-store.test")
    monkeypatch.setenv("OBJECT_STORE_BUCKET", "synthetic-recordings")
    monkeypatch.setenv("MINIO_ROOT_USER", "synthetic-user")
    monkeypatch.setenv("MINIO_ROOT_PASSWORD", "synthetic-password")

    client = Mock()
    client.head_bucket.side_effect = _client_error("403")
    with (
        patch("app.infra.ensure_bucket.boto3.client", return_value=client),
        pytest.raises(ClientError),
    ):
        ensure_bucket()

    client.create_bucket.assert_not_called()
