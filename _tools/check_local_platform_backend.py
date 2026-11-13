"""QA-only backend probe, executed inside the disposable API container.

Not a production endpoint. Uses real DB/S3/queue/API and synthetic identities.
Stdout is private JSON consumed by the host; never echo it into evidence.
"""
import asyncio
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import secrets
import sys
import uuid
from urllib.parse import urlsplit


def semantic(value):
    if isinstance(value, dict):
        return {key: (urlsplit(item)._replace(query='', fragment='').geturl()
                      if key == 'url' and isinstance(item, str) else semantic(item))
                for key, item in value.items()}
    if isinstance(value, list):
        return [semantic(item) for item in value]
    return value

import aio_pika
import boto3
from botocore.config import Config
import httpx
from sqlalchemy import select

from app.auth.passwords import hash_password
from app.infra.database import create_engine, create_session_factory
from app.infra.models import User
from app.infra.object_store import create_object_store
from app.infra.queue import create_job_queue


async def probe(origin):
    engine = create_engine()
    factory = create_session_factory(engine)
    password = secrets.token_urlsafe(32)
    users = [str(uuid.uuid4()), str(uuid.uuid4())]
    checks = []
    try:
        async with factory() as session, session.begin():
            for index, identity in enumerate(users):
                session.add(User(id=identity, email=f'qa-{identity}@example.invalid',
                                 name=f'QA synthetic {index}', password_hash=hash_password(password),
                                 is_sales=True, created_at=datetime.now(timezone.utc)))
        async with factory() as session:
            persisted = (await session.execute(select(User.id).where(User.id.in_(users)))).scalars().all()
            assert set(persisted) == set(users), 'Database write/read mismatch'
        checks.append('database-write-read')
    finally:
        await engine.dispose()

    queue = create_job_queue()
    topic = 'qa-' + uuid.uuid4().hex
    event = asyncio.Event()
    payload = {'qa': uuid.uuid4().hex}

    async def handle(message):
        assert message == payload, 'Queue payload mismatch'
        event.set()

    await queue.connect()
    try:
        await queue.subscribe(topic, handle)
        await queue.publish(topic, payload)
        await asyncio.wait_for(event.wait(), timeout=10)
        await asyncio.sleep(0.1)  # consumer sends ack after handler returns
    finally:
        await queue.disconnect()
    connection = await aio_pika.connect_robust(os.environ['QUEUE_BROKER_URL'])
    try:
        channel = await connection.channel()
        actual = await channel.declare_queue(topic, passive=True)
        assert actual.declaration_result.message_count == 0, 'Queue message was not acked'
        await actual.delete()
    finally:
        await connection.close()
    checks.append('queue-publish-consume-ack')

    store = create_object_store()
    reference = 'qa/' + uuid.uuid4().hex
    await store.save(reference, b'qa-storage-roundtrip', content_type='application/octet-stream')
    try:
        assert await store.get(reference) == b'qa-storage-roundtrip', 'S3 write/read mismatch'
    finally:
        await store.delete(reference)
    checks.append('storage-write-read')

    # Only the disposable bucket: exact portal origin, no wildcard/public ACL.
    s3 = boto3.client('s3', endpoint_url=os.environ['OBJECT_STORE_ENDPOINT'],
                      aws_access_key_id=os.environ['MINIO_ROOT_USER'],
                      aws_secret_access_key=os.environ['MINIO_ROOT_PASSWORD'],
                      config=Config(signature_version='s3v4'))
    s3.put_bucket_cors(Bucket=os.environ['OBJECT_STORE_BUCKET'], CORSConfiguration={'CORSRules': [{
        'AllowedOrigins': [origin], 'AllowedMethods': ['GET', 'HEAD'],
        'AllowedHeaders': ['range'], 'ExposeHeaders': ['Content-Range', 'Accept-Ranges'], 'MaxAgeSeconds': 60}]})

    async with httpx.AsyncClient(timeout=30, follow_redirects=False) as client:
        tokens = []
        for identity in users:
            response = await client.post('http://127.0.0.1:8000/api/v1/auth/login', json={
                'email': f'qa-{identity}@example.invalid', 'password': password})
            assert response.status_code == 200, 'Real login failed'
            tokens.append(response.json()['access_token'])
        checks.append('real-login-two-users')
        for payload, expected in [({}, 422), ({'email': 'missing@example.invalid', 'password': password}, 401)]:
            direct = await client.post('http://127.0.0.1:8000/api/v1/auth/login', json=payload)
            proxied = await client.post('http://portal/api/v1/auth/login', json=payload)
            assert direct.status_code == proxied.status_code == expected, 'Login error status mismatch'
            assert direct.json() == proxied.json(), 'Login error body mismatch'
        checks.append('proxy-real-401-422-errors')
        headers = {'Authorization': 'Bearer ' + tokens[0]}
        meeting = str(uuid.uuid4())
        medium = Path('/tmp/qa-media.webm').read_bytes()
        response = await client.post('http://portal/api/v1/ingestion/upload', headers=headers,
                                     files={'audio': ('synthetic.webm', medium, 'video/webm')},
                                     data={'data': json.dumps({'meeting_id': meeting,
                                         'idempotency_key': uuid.uuid4().hex, 'capture_origin': 'web_upload',
                                         'duration_seconds': 2, 'video_presence': 'muxed',
                                         'title': 'QA synthetic audiovisual fixture'})})
        assert response.status_code == 200, f'Upload failed with status {response.status_code}'
        checks.append('proxy-real-multipart-upload')

        for path in ['/api/v1/meetings/?probe=real', '/api/v1/meetings/' + meeting,
                     '/api/v1/meetings/missing', '/api/v1/meetings/' + meeting + '/playback']:
            for token in [tokens[0], tokens[1], None]:
                auth = {'Authorization': 'Bearer ' + token} if token else {}
                direct = await client.get('http://127.0.0.1:8000' + path, headers=auth)
                proxied = await client.get('http://portal' + path, headers=auth)
                assert direct.status_code == proxied.status_code, 'Proxy status mismatch'
                assert semantic(direct.json()) == semantic(proxied.json()), 'Proxy semantic body mismatch'
                if meeting in path:
                    expected = 200 if token == tokens[0] else 404 if token else 401
                    assert direct.status_code == expected, 'Meeting authorization mismatch'
        checks.append('proxy-direct-and-owner-other-anonymous')
        response = await client.get(f'http://portal/api/v1/meetings/{meeting}/playback', headers=headers)
        manifest = response.json()
        return {'checks': checks, 'meetingId': meeting, 'tokens': tokens,
                'manifest': manifest, 'mediumSize': len(medium)}


if __name__ == '__main__':
    try:
        result = asyncio.run(probe(sys.argv[1]))
    except AssertionError as error:
        result = {'error': str(error)}  # all assertions use fixed non-secret messages
    except Exception as error:
        result = {'error': type(error).__name__}  # SDK errors may include private URLs
    print(json.dumps(result))
