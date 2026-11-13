"""T11 #650: only a proven absent key can be called missing."""

import os
import uuid
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
async def test_generic_head_404_requires_accessible_bucket_and_exact_nosuchkey(store):
    store._client.head_object.side_effect = error("404", 404)
    store._client.get_object_attributes.side_effect = error("NoSuchKey", 404)
    assert await store.inspect("synthetic/exact.webm") == "missing"
    store._client.head_bucket.assert_called_once_with(Bucket="synthetic-bucket")
    store._client.get_object_attributes.assert_called_once_with(
        Bucket="synthetic-bucket", Key="synthetic/exact.webm", ObjectAttributes=["ObjectSize"],
    )
    store._client.get_object.assert_not_called()


@pytest.mark.asyncio
async def test_bucket_404_never_confirms_key_absence(store):
    store._client.head_object.side_effect = error("404", 404)
    store._client.head_bucket.side_effect = error("404", 404)
    with pytest.raises(ClientError):
        await store.inspect("synthetic/exact.webm")
    store._client.get_object_attributes.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize(("code", "status"), [("NoSuchBucket", 404),
                                                  ("AccessDenied", 403), ("SlowDown", 503),
                                                  ("InternalError", 500)])
async def test_ambiguous_and_permission_errors_propagate(store, code, status):
    store._client.head_object.side_effect = error(code, status)
    with pytest.raises(ClientError):
        await store.inspect("synthetic/exact.webm")


@pytest.mark.asyncio
@pytest.mark.parametrize("code", ["404", "AccessDenied", "NoSuchBucket"])
async def test_attributes_without_exact_nosuchkey_fail_closed(store, code):
    store._client.head_object.side_effect = error("404", 404)
    store._client.get_object_attributes.side_effect = error(code, 404 if code != "AccessDenied" else 403)
    with pytest.raises(ClientError):
        await store.inspect("synthetic/exact.webm")


@pytest.mark.asyncio
async def test_network_error_propagates(store):
    store._client.head_object.side_effect = EndpointConnectionError(endpoint_url="http://localhost:9000")
    with pytest.raises(EndpointConnectionError):
        await store.inspect("synthetic/exact.webm")


@pytest.mark.asyncio
async def test_real_s3_compatible_metadata_only_when_dedicated_qa_store():
    endpoint = os.environ.get("OBJECT_STORE_ENDPOINT")
    if not (endpoint and os.environ.get("OBJECT_STORE_BUCKET") == "synthetic-qa"
            and os.environ.get("SAURI_QA_POSTGRES_URL")):
        pytest.skip("dedicated disposable S3 QA store required")
    store = S3ObjectStore(endpoint_url=endpoint, bucket="synthetic-qa",
                          access_key=os.environ["MINIO_ROOT_USER"],
                          secret_key=os.environ["MINIO_ROOT_PASSWORD"])
    assert await store.inspect("qa/synthetic.webm") == "available"
    assert await store.inspect(f"qa/absent-{uuid.uuid4()}.webm") == "missing"
    absent_bucket = S3ObjectStore(endpoint_url=endpoint, bucket="synthetic-qa-absent",
                                  access_key=os.environ["MINIO_ROOT_USER"],
                                  secret_key=os.environ["MINIO_ROOT_PASSWORD"])
    with pytest.raises(ClientError):
        await absent_bucket.inspect(f"qa/absent-{uuid.uuid4()}.webm")
