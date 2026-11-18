"""Real FileResponse reads, signed object scopes, and property 5 (exact Range)."""

import base64
import json
import tempfile
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlsplit

import httpx
import pytest
from fastapi import FastAPI
from hypothesis import given
from hypothesis import strategies as st

from app.infra.object_store_fs import FilesystemObjectStore
from app.media.router import router
from app.media.tokens import sign_media_token
from tests.meetings.conftest import api_db_url as api_db_url

KEY = "recordings/meeting/recording/audio"
app = FastAPI()
app.include_router(router)


def environment(root: Path) -> dict[str, str]:
    secret = root / "capability-key"
    secret.write_text("synthetic-media-signing-key")
    return {
        "OBJECT_STORE_KIND": "filesystem", "SAURI_RECORDINGS_DIR": str(root),
        "SAURI_RECORDING_CAPABILITY_KEY_FILE": str(secret),
    }


@st.composite
def ranges(draw):
    content = draw(st.binary(min_size=1, max_size=10000))
    start = draw(st.integers(min_value=0, max_value=len(content) - 1))
    end = draw(st.integers(min_value=start, max_value=len(content) - 1))
    return content, start, end


@given(case=ranges())
async def test_property_5_random_ranges_have_exact_bytes(case) -> None:
    content, start, end = case
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        with patch.dict("os.environ", environment(root)):
            store = FilesystemObjectStore(root)
            await store.save(KEY, content)
            url = await store.temporary_read_url(KEY)
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app)) as client:
                response = await client.get(url, headers={"Range": f"bytes={start}-{end}"})
            assert response.status_code == 206
            assert response.content == content[start:end + 1]
            assert response.headers["content-range"] == f"bytes {start}-{end}/{len(content)}"
            assert int(response.headers["content-length"]) == end - start + 1


@pytest.mark.parametrize(("key", "content", "mime"), [
    (KEY, b"\x1a\x45\xdf\xa3" + b"synthetic-webm", "audio/webm"),
    (KEY.replace("audio", "video"), b"\x00\x00\x00\x20ftypisom", "video/mp4"),
    (KEY.replace("audio", "thumbnail.jpg"), b"\xff\xd8\xff" + b"synthetic-jpeg", "image/jpeg"),
])
async def test_read_download_and_restart_have_correct_headers(tmp_path, key, content, mime) -> None:
    with patch.dict("os.environ", environment(tmp_path)):
        await FilesystemObjectStore(tmp_path).save(key, content, mime)
        store = FilesystemObjectStore(tmp_path)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app)) as client:
            response = await client.get(await store.temporary_read_url(key))
            assert response.status_code == 200 and response.content == content
            assert response.headers["content-type"] == mime
            assert response.headers["content-disposition"].startswith("inline;")
            filename = 'Meeting "one"\r\n test.mp4'
            response = await client.get(await store.temporary_download_url(key, filename))
            assert response.status_code == 200 and response.content == content
            assert response.headers["content-type"] == mime
            assert response.headers["content-disposition"].startswith("attachment;")
            assert "%0D%0A" in response.headers["content-disposition"]
            assert response.headers["cache-control"] == "private, no-store"


@pytest.mark.parametrize("attack", ["expired", "tampered", "cross-key", "wrong-secret", "malformed"])
async def test_invalid_capabilities_return_403(tmp_path, attack) -> None:
    with patch.dict("os.environ", environment(tmp_path)):
        store = FilesystemObjectStore(tmp_path)
        await store.save(KEY, b"private-a")
        await store.save("recordings/other/recording/audio", b"private-b")
        token = sign_media_token(KEY, -1 if attack == "expired" else 60, "audio/webm")
        payload, signature = token.split(".")
        if attack == "tampered":
            token = f"{payload}.{'0' * 64}"
        elif attack == "cross-key":
            claims = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
            claims["key"] = "recordings/other/recording/audio"
            forged = base64.urlsafe_b64encode(json.dumps(claims).encode()).rstrip(b"=").decode()
            token = f"{forged}.{signature}"
        elif attack == "wrong-secret":
            (tmp_path / "capability-key").write_text("another-key")
        elif attack == "malformed":
            token = "not-a-token"
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get(f"/api/v1/media/{token}")
        assert response.status_code == 403
        assert b"private" not in response.content


@pytest.mark.parametrize("key", ["../secret", "/etc/passwd", "recordings/../secret", "audio\0", "link/secret"])
async def test_even_signed_escaping_paths_return_403(tmp_path, key) -> None:
    root = tmp_path / "root"
    root.mkdir()
    (root / "link").symlink_to(tmp_path, target_is_directory=True)
    with patch.dict("os.environ", environment(root)):
        token = sign_media_token(key, 60, "audio/webm")
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            assert (await client.get(f"/api/v1/media/{token}")).status_code == 403


async def test_suffix_open_ended_and_invalid_ranges(tmp_path) -> None:
    with patch.dict("os.environ", environment(tmp_path)):
        store = FilesystemObjectStore(tmp_path)
        await store.save(KEY, b"0123456789")
        url = await store.temporary_read_url(KEY)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app)) as client:
            for value, expected in [("bytes=-3", b"789"), ("bytes=5-", b"56789")]:
                response = await client.get(url, headers={"Range": value})
                assert response.status_code == 206 and response.content == expected
            assert (await client.get(url, headers={"Range": "bytes=99-100"})).status_code == 416


async def test_origin_is_configurable_and_s3_mode_does_not_serve_files(tmp_path) -> None:
    with patch.dict("os.environ", {**environment(tmp_path), "SAURI_PUBLIC_API_ORIGIN": "http://127.0.0.1:8999/"}):
        store = FilesystemObjectStore(tmp_path)
        await store.save(KEY, b"data")
        url = await store.temporary_read_url(KEY)
        assert url.startswith("http://127.0.0.1:8999/api/v1/media/")
        with patch.dict("os.environ", {"OBJECT_STORE_KIND": "s3"}):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
                assert (await client.get(urlsplit(url).path)).status_code == 404


async def test_default_origin_follows_the_configured_api_port(tmp_path) -> None:
    # An empty SAURI_PUBLIC_API_ORIGIN counts as unset: the origin comes from SAURI_API_PORT.
    overrides = {**environment(tmp_path), "SAURI_API_PORT": "18100", "SAURI_PUBLIC_API_ORIGIN": ""}
    with patch.dict("os.environ", overrides):
        store = FilesystemObjectStore(tmp_path)
        await store.save(KEY, b"data")
        url = await store.temporary_read_url(KEY)
    assert url.startswith("http://localhost:18100/api/v1/media/")


async def test_signatures_reuse_raw_existing_key_including_newline(tmp_path) -> None:
    import hashlib
    import hmac

    with patch.dict("os.environ", environment(tmp_path)):
        secret = b"synthetic-key-with-newline\n"
        (tmp_path / "capability-key").write_bytes(secret)
        payload, signature = sign_media_token(KEY, 60, "audio/webm").split(".")
        assert signature == hmac.new(secret, payload.encode(), hashlib.sha256).hexdigest()


async def test_meetings_use_filesystem_urls_end_to_end(tmp_path, api_db_url) -> None:
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.auth.dependencies import get_current_user
    from app.auth.schemas import AuthenticatedUser
    from app.main import create_app
    from app.media.tokens import verify_media_token
    from tests.thumbnails.test_service import add_recording

    engine = create_async_engine(api_db_url)
    try:
        meeting_id, _ = await add_recording(async_sessionmaker(engine, expire_on_commit=False))
    finally:
        await engine.dispose()
    with patch.dict("os.environ", environment(tmp_path)):
        store = FilesystemObjectStore(tmp_path)
        content = b"\x1a\x45\xdf\xa3synthetic-webm"
        await store.save(f"recordings/{meeting_id}/a/audio", content)
        application = create_app()
        application.dependency_overrides[get_current_user] = lambda: AuthenticatedUser(
            id="owner", email="owner@test.invalid", name="Owner", is_sales=True,
        )
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=application), base_url="http://test") as client:
            playback = await client.get(f"/api/v1/meetings/{meeting_id}/playback")
            assert playback.status_code == 200, playback.text
            url = playback.json()["audio_source"]["url"]
            assert url.startswith("http://localhost:8000/api/v1/media/")
            assert verify_media_token(url.rsplit("/", 1)[1])["key"] == f"recordings/{meeting_id}/a/audio"
            response = await client.get(url, headers={"Range": "bytes=2-7"})
            assert response.status_code == 206 and response.content == content[2:8]
            download = await client.get(f"/api/v1/meetings/{meeting_id}/media-download")
            assert download.status_code == 200, download.text
            response = await client.get(download.json()["url"])
            assert response.status_code == 200 and response.content == content
            assert response.headers["content-disposition"].startswith("attachment;")
