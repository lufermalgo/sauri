"""T11 #650: only a proven absent key can be called missing."""

from unittest.mock import MagicMock

import pytest
from botocore.exceptions import ClientError, EndpointConnectionError

from app.infra.object_store_s3 import S3ObjectStore


def error(code, status):
    return ClientError({"Error": {"Code": code, "Message": "synthetic"},
                        "ResponseMetadata": {"HTTPStatusCode": status}}, "HeadObject")


@pytest.fixture
def store():
    obj = S3ObjectStore(endpoint_url="http://localhost:9000", bucket="synthetic-bucket",
                        access_key="synthetic", secret_key="synthetic")
    obj._client = MagicMock()
    return obj


@pytest.mark.asyncio
async def test_head_exact_key_no_download(store):
    assert await store.inspect("synthetic/exact.webm") == "available"
    store._client.head_object.assert_called_once_with(Bucket="synthetic-bucket", Key="synthetic/exact.webm")
    store._client.get_object.assert_not_called()


@pytest.mark.asyncio
async def test_only_nosuchkey_is_missing(store):
    store._client.head_object.side_effect = error("NoSuchKey", 404)
    assert await store.inspect("synthetic/exact.webm") == "missing"


@pytest.mark.asyncio
@pytest.mark.parametrize(("code", "status"), [("404", 404), ("NoSuchBucket", 404),
                                                  ("AccessDenied", 403), ("SlowDown", 503),
                                                  ("InternalError", 500)])
async def test_ambiguous_and_permission_errors_propagate(store, code, status):
    store._client.head_object.side_effect = error(code, status)
    with pytest.raises(ClientError):
        await store.inspect("synthetic/exact.webm")


@pytest.mark.asyncio
async def test_network_error_propagates(store):
    store._client.head_object.side_effect = EndpointConnectionError(endpoint_url="http://localhost:9000")
    with pytest.raises(EndpointConnectionError):
        await store.inspect("synthetic/exact.webm")
