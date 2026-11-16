"""A fake chat provider on 127.0.0.1 that counts connections and open streams (no real provider, no key)."""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from http import HTTPStatus
from typing import Any

KEY = "sk-test-KEY-0123456789abcdef"
SUMMARY = {"title": "Weekly sync", "key_points": [{"text": "Ship it", "sources": [{"passage_id": "p1"}]}]}


@dataclass
class Seen:
    method: str
    path: str
    headers: dict[str, str]
    body: bytes

    def json(self) -> dict[str, Any]:
        result: dict[str, Any] = json.loads(self.body)
        return result


Handler = Callable[[Seen, asyncio.StreamWriter], Awaitable[None]]


@dataclass
class FakeProvider:
    handler: Handler
    seen: list[Seen] = field(default_factory=list)
    connections: int = 0
    open_streams: int = 0
    port: int = 0
    _server: asyncio.Server | None = None

    async def start(self) -> None:
        self._server = await asyncio.start_server(self._client, "127.0.0.1", 0)
        self.port = self._server.sockets[0].getsockname()[1]

    async def close(self) -> None:
        assert self._server is not None
        self._server.close()
        await self._server.wait_closed()

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    async def _client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        self.connections += 1
        try:
            head = (await reader.readuntil(b"\r\n\r\n")).decode()
            lines = head.split("\r\n")
            method, path, _version = lines[0].split(" ")
            headers = {k.lower(): v.strip() for k, v in (line.split(":", 1) for line in lines[1:] if line)}
            body = await reader.readexactly(int(headers.get("content-length", "0")))
        except (asyncio.IncompleteReadError, ConnectionError):
            writer.close()
            return
        request = Seen(method, path, headers, body)
        self.seen.append(request)
        self.open_streams += 1
        work: asyncio.Task[None] = asyncio.ensure_future(self.handler(request, writer))
        eof = asyncio.create_task(reader.read(1))  # a client that closes its socket ends the "stream"
        try:
            await asyncio.wait({work, eof}, return_when=asyncio.FIRST_COMPLETED)
        finally:
            self.open_streams -= 1
            work.cancel()
            eof.cancel()
            await asyncio.gather(work, eof, return_exceptions=True)
            writer.close()


async def send_head(writer: asyncio.StreamWriter, status: int, headers: dict[str, str]) -> None:
    lines = [f"HTTP/1.1 {status} {HTTPStatus(status).phrase}", *(f"{k}: {v}" for k, v in headers.items())]
    writer.write(("\r\n".join([*lines, "Connection: close"]) + "\r\n\r\n").encode())
    await writer.drain()


def data(obj: Any) -> str:
    return f"data: {obj if isinstance(obj, str) else json.dumps(obj)}\n\n"


def openai_events(parts: list[str], *, usage: tuple[int, int] = (11, 7)) -> list[str]:
    base = {"id": "chatcmpl-1", "model": "m-real"}
    events = [
        data({**base, "choices": [{"index": 0, "delta": {"content": part}, "finish_reason": None}]}) for part in parts
    ]
    events.append(data({**base, "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]}))
    events.append(data({**base, "choices": [], "usage": {"prompt_tokens": usage[0], "completion_tokens": usage[1]}}))
    events.append(data("[DONE]"))
    return events


def anthropic_events(parts: list[str]) -> list[str]:
    message = {"id": "msg_1", "model": "m-real", "content": [], "usage": {"input_tokens": 11}}
    events = [data({"type": "message_start", "message": message})]
    events += [
        data({"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": part}})
        for part in parts
    ]
    events.append(data({"type": "message_delta", "delta": {"stop_reason": "end_turn"}, "usage": {"output_tokens": 7}}))
    events.append(data({"type": "message_stop"}))
    return events


def replying(events: list[str]) -> Handler:
    async def handler(_seen: Seen, writer: asyncio.StreamWriter) -> None:
        await send_head(writer, 200, {"Content-Type": "text/event-stream"})
        for event in events:
            writer.write(event.encode())
            await writer.drain()

    return handler


def failing(status: int, body: Any, headers: dict[str, str] | None = None) -> Handler:
    async def handler(_seen: Seen, writer: asyncio.StreamWriter) -> None:
        payload = json.dumps(body).encode()
        await send_head(
            writer, status,
            {"Content-Type": "application/json", "Content-Length": str(len(payload)), **(headers or {})},
        )
        writer.write(payload)
        await writer.drain()

    return handler


async def hang_before_any_byte(_seen: Seen, _writer: asyncio.StreamWriter) -> None:
    await asyncio.sleep(60)


def hang_after_first_event(events: list[str]) -> Handler:
    async def handler(_seen: Seen, writer: asyncio.StreamWriter) -> None:
        await send_head(writer, 200, {"Content-Type": "text/event-stream"})
        writer.write(events[0].encode())
        await writer.drain()
        await asyncio.sleep(60)

    return handler


async def wait_until(condition: Callable[[], bool], *, limit_s: float) -> float:
    started = time.monotonic()
    while not condition():
        assert time.monotonic() - started < limit_s, "condition not reached in time"
        await asyncio.sleep(0.01)
    return time.monotonic() - started
