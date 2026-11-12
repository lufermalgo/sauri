import { afterEach, beforeEach, expect, it, vi } from "vitest";
import * as fc from "fast-check";
import { IDBFactory, IDBKeyRange } from "fake-indexeddb";
import { createCompletion, getCompletion, storeChunk } from "./recording-db";

// Exercise the actual service-worker listeners, upload queue, and completion record.
// Only the HTTP replies and Chrome boundary are synthetic; no production functions are mocked.
type Message = { type: string; sessionId?: string; size?: number; mimeType?: string };
type Listener = (message: Message, sender: object, respond: (value: unknown) => void) => unknown;
type ProcessState = "queued" | "joining" | "recording" | "transcribing" | "failed" | "completed";

interface Scenario {
  state: ProcessState;
  transcript: boolean;
  video: boolean;
  sameMeeting: boolean;
  sameRecording: boolean;
}

async function runScenario(scenario: Scenario, sessionId: string = crypto.randomUUID()) {
  vi.resetModules();
  vi.stubGlobal("indexedDB", new IDBFactory());
  vi.stubGlobal("IDBKeyRange", IDBKeyRange);
  const meetingId = crypto.randomUUID();
  const recordingId = crypto.randomUUID();
  const otherMeetingId = crypto.randomUUID();
  const otherRecordingId = crypto.randomUUID();
  // A conflicting persisted recording identity must not be remapped by an ingestion retry.
  await createCompletion({ sessionId, meetingId, recordingId: scenario.sameRecording ? undefined : otherRecordingId,
    provider: "meet", capturedTabId: 42, status: "capturing", updatedAt: 1 });
  await storeChunk(sessionId, new Blob(["synthetic media"], { type: "video/webm" }));

  const fetched: string[] = [];
  vi.stubGlobal("fetch", vi.fn(async (input: string, init?: RequestInit) => {
    const url = String(input);
    fetched.push(url);
    if (init?.method === "POST") {
      // The ingestion response has recording_id and state, not meeting_id.
      return new Response(JSON.stringify({ recording_id: recordingId, state: scenario.state }), { status: 200 });
    }
    if (url.endsWith("/transcript")) return scenario.transcript
      ? new Response(JSON.stringify({ meeting_id: scenario.sameMeeting ? meetingId : otherMeetingId, transcript_id: "transcript" }))
      : new Response(null, { status: 404 });
    if (url.endsWith("/playback")) return new Response(JSON.stringify({
      meeting_id: scenario.sameMeeting ? meetingId : otherMeetingId,
      video_presence: scenario.video ? "muxed" : "absent",
      audio_source: { source_id: "synthetic-audio", url: "https://example.invalid/audio", mime_type: "video/webm" },
      muxed_video_source: scenario.video ? { source_id: "synthetic-video", url: "https://example.invalid/video", mime_type: "video/webm" } : null,
      video_sources: [],
    }));
    return new Response(JSON.stringify({ meeting_id: scenario.sameMeeting ? meetingId : otherMeetingId,
      process_state: scenario.state }));
  }));

  let listener: Listener | undefined;
  let state: Record<string, unknown> = { status: "recording", sessionId, tabId: 42 };
  const sent = vi.fn(async () => ({ ok: true }));
  vi.stubGlobal("chrome", {
    action: { onClicked: { addListener: vi.fn() }, setBadgeText: vi.fn(), setBadgeBackgroundColor: vi.fn() },
    alarms: { create: vi.fn(), onAlarm: { addListener: vi.fn() } },
    runtime: {
      onInstalled: { addListener: vi.fn() }, onStartup: { addListener: vi.fn() },
      onMessage: { addListener: (fn: Listener) => { listener = fn; } },
      getURL: (path: string) => path, getContexts: vi.fn(async () => []), sendMessage: sent,
    },
    sidePanel: { setPanelBehavior: vi.fn(async () => undefined), open: vi.fn() },
    storage: {
      session: { get: vi.fn(async () => ({ sauriState: state })), set: vi.fn(async (value: { sauriState: Record<string, unknown> }) => { state = value.sauriState; }) },
      sync: { get: vi.fn(async () => ({})) },
    },
    tabs: { onRemoved: { addListener: vi.fn() }, query: vi.fn(async () => []), sendMessage: vi.fn(async () => undefined), create: vi.fn() },
  });
  await import("./background");
  await new Promise<void>((resolve) => listener!({ type: "stop-capture" }, {}, () => resolve()));
  expect(sent).toHaveBeenCalledWith({ type: "stop-recording", sessionId });
  listener!({ type: "recording-stopped", sessionId, size: 15, mimeType: "video/webm" }, {}, vi.fn());
  // Do not open the queue DB before enqueueUpload creates its object store.
  await vi.waitFor(() => expect(fetched).toContain("http://localhost:8000/api/v1/ingestion/upload"), { timeout: 2000, interval: 5 });
  // Listener dispatches upload asynchronously; wait for the real queue transaction.
  await vi.waitFor(async () => {
    const db = await new Promise<IDBDatabase>((resolve, reject) => {
      const request = indexedDB.open("sauri-upload-queue", 2);
      request.onsuccess = () => resolve(request.result);
      request.onerror = () => reject(request.error);
    });
    try {
      const jobs = await new Promise<Array<{ status: string }>>((resolve, reject) => {
        const request = db.transaction("jobs", "readonly").objectStore("jobs").getAll();
        request.onsuccess = () => resolve(request.result);
        request.onerror = () => reject(request.error);
      });
      expect(jobs).toHaveLength(1);
      expect(jobs[0].status).toBe("done");
    } finally { db.close(); }
  }, { timeout: 2000, interval: 5 });
  return { completion: await getCompletion(sessionId), fetched, meetingId, recordingId };
}

beforeEach(() => {
  vi.spyOn(console, "log").mockImplementation(() => undefined);
  vi.spyOn(console, "warn").mockImplementation(() => undefined);
});
afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks(); });

const state = fc.constantFrom<ProcessState>("queued", "joining", "recording", "transcribing", "failed", "completed");
const combinations = fc.record({ state, transcript: fc.boolean(), video: fc.boolean(), sameMeeting: fc.boolean(), sameRecording: fc.boolean() });
const ready: Scenario = { state: "completed", transcript: true, video: true, sameMeeting: true, sameRecording: true };
const statusUrl = (id: string) => `http://localhost:8000/api/v1/meetings/${id}`;

it("checks the same meeting's status and never marks incomplete or mismatched assets ready (100 generated cases)", async () => {
  // Include each important edge deterministically, then sample 100 more cases.
  // Collect behavioral violations so the RED run actually executes all generated cases.
  const edges: Scenario[] = [
    ...(["queued", "joining", "recording", "transcribing", "failed"] as ProcessState[]).map(state => ({ ...ready, state })),
    { ...ready, transcript: false }, { ...ready, video: false },
    { ...ready, sameMeeting: false }, { ...ready, sameRecording: false },
  ];
  const cases = [...edges, ...fc.sample(combinations.filter(c => c.state !== "completed" || !c.transcript || !c.video || !c.sameMeeting || !c.sameRecording), 100)];
  let violations = 0;
  let counterexample = "";
  for (const [index, scenario] of cases.entries()) {
    const { completion, fetched, meetingId } = await runScenario(scenario);
    if (!fetched.includes(statusUrl(meetingId)) || completion?.status === "processing_succeeded") {
      violations++;
      if (!counterexample) counterexample = `${index}: ${JSON.stringify(scenario)}; status=${completion?.status}; reads=${fetched.join(",")}`;
    }
  }
  expect(violations, `Checked ${cases.length} cases; counterexample: ${counterexample}`).toBe(0);
}, 60000);

it("marks success only after checking completed status, transcript and playable video for the same mapping (100 generated IDs)", async () => {
  let violations = 0;
  let counterexample = "";
  for (const [index, sessionId] of fc.sample(fc.uuid(), 100).entries()) {
    const { completion, fetched, meetingId, recordingId } = await runScenario(ready, sessionId);
    const required = [statusUrl(meetingId), `${statusUrl(meetingId)}/transcript`, `${statusUrl(meetingId)}/playback`];
    if (completion?.status !== "processing_succeeded" || completion.meetingId !== meetingId ||
        completion.recordingId !== recordingId || required.some(url => !fetched.includes(url))) {
      violations++;
      if (!counterexample) counterexample = `${index}: meeting=${meetingId}; status=${completion?.status}; reads=${fetched.join(",")}`;
    }
  }
  expect(violations, `Checked 100 cases; counterexample: ${counterexample}`).toBe(0);
}, 60000);
