// @vitest-environment jsdom
// @vitest-environment-options {"url":"http://localhost:8000/"}
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import * as api from "./api";
import { createMemoryStorage } from "./test/storage";

const upload = { duration_seconds: 1, meeting_id: "synthetic-id", idempotency_key: "synthetic-key",
  capture_origin: "web_upload" as const, video_presence: "absent" as const, title: "Synthetic" };
const result = { meeting_id: "synthetic-id", recording_id: "recording-id", state: "transcribing" };
const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status });

beforeEach(async () => {
  vi.stubGlobal("localStorage", createMemoryStorage());
  localStorage.setItem(api.TOKEN_KEY, "stale-password-token");
  vi.stubGlobal("fetch", vi.fn()
    .mockResolvedValueOnce(json({ mode: "local", ready: true }))
    .mockResolvedValueOnce(json({ name: "Local Tester", email: "local@sauri.local" })));
  expect(api.canDetectLocalMode()).toBe(true);
  expect(await api.detectLocalSession()).toEqual({ name: "Local Tester", email: "local@sauri.local", mode: "local" });
});

afterEach(async () => {
  vi.stubGlobal("fetch", vi.fn(async () => json({}, 404)));
  await api.detectLocalSession();
  vi.unstubAllGlobals();
});

it("sends neither JSON nor multipart requests with a stale bearer token", async () => {
  const fetch = vi.fn().mockResolvedValueOnce(json([])).mockResolvedValueOnce(json(result));
  vi.stubGlobal("fetch", fetch);
  await api.listMeetings();
  await api.uploadRecording(new File(["synthetic"], "test.webm"), upload);
  for (const [, init] of fetch.mock.calls) expect(new Headers(init.headers).has("Authorization")).toBe(false);
  expect(new Headers(fetch.mock.calls[1][1].headers).has("Content-Type")).toBe(false);
});

it("does not clear password storage or emit logout on a local 401", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => json({}, 401)));
  const unauthorized = vi.fn();
  window.addEventListener("sauri:unauthorized", unauthorized);
  try {
    await expect(api.listMeetings()).rejects.toThrow("Error 401");
    expect(localStorage.getItem(api.TOKEN_KEY)).toBe("stale-password-token");
    expect(unauthorized).not.toHaveBeenCalled();
  } finally {
    window.removeEventListener("sauri:unauthorized", unauthorized);
  }
});

it.each([200, 401])("uploads via XHR without a token and preserves local session for status %s", async (status) => {
  localStorage.removeItem(api.TOKEN_KEY);
  const setHeader = vi.fn();
  const unauthorized = vi.fn();
  window.addEventListener("sauri:unauthorized", unauthorized);
  class Xhr {
    upload = {};
    status = status;
    responseText = JSON.stringify(result);
    onload = () => {};
    open = vi.fn();
    setRequestHeader = setHeader;
    send() { this.onload(); }
  }
  vi.stubGlobal("XMLHttpRequest", Xhr);
  try {
    const pending = api.uploadWithProgress(new File(["synthetic"], "test.webm"), upload, vi.fn());
    if (status === 200) await expect(pending).resolves.toEqual(result);
    else await expect(pending).rejects.toThrow();
    expect(setHeader).not.toHaveBeenCalled();
    expect(unauthorized).not.toHaveBeenCalled();
  } finally {
    window.removeEventListener("sauri:unauthorized", unauthorized);
  }
});
