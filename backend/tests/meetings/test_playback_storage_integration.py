"""Integration contract for signed playback delivery from S3-compatible storage.

Run only against a disposable bucket configured with the browser's frontend
origin in its object-store CORS policy. Missing configuration is a failure,
not a reason to fall back to a public URL or another delivery path.
"""

from __future__ import annotations

import os
import uuid

import httpx
import pytest

from app.infra.object_store_s3 import S3ObjectStore

_REQUIRED_ENV = (
    "OBJECT_STORE_ENDPOINT",
    "OBJECT_STORE_BUCKET",
    "MINIO_ROOT_USER",
    "MINIO_ROOT_PASSWORD",
    "PLAYBACK_TEST_FRONTEND_ORIGIN",
)


@pytest.mark.asyncio
async def test_signed_playback_source_supports_range_and_frontend_cors() -> None:
    missing = [name for name in _REQUIRED_ENV if not os.environ.get(name)]
    if len(missing) == len(_REQUIRED_ENV):
        pytest.skip(
            "requires a disposable S3-compatible bucket (MinIO/RustFS) in "
            + ", ".join(_REQUIRED_ENV)
        )
    if missing:
        pytest.fail(f"incomplete playback storage configuration; missing: {', '.join(missing)}")
    endpoint = os.environ["OBJECT_STORE_ENDPOINT"]
    bucket = os.environ["OBJECT_STORE_BUCKET"]
    access_key = os.environ["MINIO_ROOT_USER"]
    secret_key = os.environ["MINIO_ROOT_PASSWORD"]
    frontend_origin = os.environ["PLAYBACK_TEST_FRONTEND_ORIGIN"]

    store = S3ObjectStore(
        endpoint_url=endpoint,
        bucket=bucket,
        access_key=access_key,
        secret_key=secret_key,
    )
    reference = f"integration-tests/playback-range/{uuid.uuid4()}.bin"
    payload = bytes(range(64))
    start, end = 9, 26

    await store.save(reference, payload, content_type="application/octet-stream")
    try:
        signed_url = await store.temporary_read_url(reference, ttl_seconds=3600)
        async with httpx.AsyncClient(follow_redirects=False, timeout=10) as client:
            preflight = await client.options(
                signed_url,
                headers={
                    "Origin": frontend_origin,
                    "Access-Control-Request-Method": "GET",
                    "Access-Control-Request-Headers": "range",
                },
            )
            assert preflight.status_code in {200, 204}, preflight.text
            assert preflight.headers.get("access-control-allow-origin") == frontend_origin
            allowed_methods = preflight.headers.get("access-control-allow-methods", "")
            assert "GET" in {method.strip().upper() for method in allowed_methods.split(",")}
            allowed_headers = preflight.headers.get("access-control-allow-headers", "")
            assert "range" in {header.strip().lower() for header in allowed_headers.split(",")}

            response = await client.get(
                signed_url,
                headers={
                    "Origin": frontend_origin,
                    "Range": f"bytes={start}-{end}",
                },
            )

        assert response.status_code == 206, response.text
        assert response.headers.get("content-range") == f"bytes {start}-{end}/{len(payload)}"
        assert response.content == payload[start : end + 1]
        assert response.headers.get("access-control-allow-origin") == frontend_origin
    finally:
        await store.delete(reference)
