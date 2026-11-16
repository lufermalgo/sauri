import { afterEach, expect, it, vi } from "vitest";
import * as fc from "fast-check";
import { IDBFactory, IDBKeyRange } from "fake-indexeddb";
import { claimReviewLaunch, createCompletion, getCompletion, setProcessingStatus, type RecordingCompletion } from "./recording-db";

type Event = "startup" | "retry" | "restart";
const sequences = fc.sample(fc.record({
  sessionId: fc.uuid(),
  events: fc.array(fc.constantFrom<Event>("startup", "retry", "restart"), { minLength: 2, maxLength: 5 }),
}), { seed: 614, numRuns: 100 });

// Only Chrome/HTTP boundaries are doubles. The worker, claim and IndexedDB are real.
// Do not invent a portal URL: recovery discovers the exact target requested by production.
async function worker(record: RecordingCompletion, crashAfterCreate = false, alreadyOpen = false) {
  vi.stubGlobal("indexedDB", new IDBFactory());
  vi.stubGlobal("IDBKeyRange", IDBKeyRange);
  await createCompletion(record);
  let startup: () => unknown;
  let alarm: (value: { name: string }) => unknown;
  const tabs: Array<{ id: number; url: string }> = alreadyOpen
    ? [{ id: 614, url: `http://localhost:5173/?meetingId=${encodeURIComponent(record.meetingId)}` }] : [];
  const boundaryErrors: string[] = [];
  const create = vi.fn(async (options: { url?: string }) => {
    const saved = await getCompletion(record.sessionId);
    if ((saved?.reviewStatus ?? saved?.status) !== "review_launch_pending") boundaryErrors.push("tab created before durable claim");
    if (!options.url) boundaryErrors.push("missing target");
    const tab = { id: 614, url: options.url ?? "" };
    tabs.push(tab);
    if (crashAfterCreate) throw new Error("synthetic worker interruption after Chrome created tab");
    return tab;
  });
  const query = vi.fn(async () => tabs.slice());
  vi.stubGlobal("fetch", vi.fn(async (input: string) => {
    const url = String(input);
    if (url.endsWith("/transcript")) return new Response(JSON.stringify({ meeting_id: record.meetingId, transcript_id: "synthetic" }));
    if (url.endsWith("/playback")) return new Response(JSON.stringify({
      meeting_id: record.meetingId, video_presence: "muxed", video_sources: [],
      audio_source: { source_id: "audio", url: "https://example.invalid/audio", mime_type: "video/webm" },
      muxed_video_source: { source_id: "video", url: "https://example.invalid/video", mime_type: "video/webm" },
    }));
    return new Response(JSON.stringify({ meeting_id: record.meetingId, recording_id: record.recordingId, process_state: "completed" }));
  }));
  vi.stubGlobal("chrome", {
    action: { onClicked: { addListener: vi.fn() }, setBadgeText: vi.fn(), setBadgeBackgroundColor: vi.fn() },
    alarms: { create: vi.fn(), onAlarm: { addListener: (fn: typeof alarm) => { alarm = fn; } } },
    runtime: {
      onInstalled: { addListener: vi.fn() }, onStartup: { addListener: (fn: typeof startup) => { startup = fn; } },
      onMessage: { addListener: vi.fn() }, getURL: (path: string) => `chrome-extension://synthetic/${path}`,
      getContexts: vi.fn(async () => []), sendMessage: vi.fn(async () => ({ ok: true })),
    },
    sidePanel: { setPanelBehavior: vi.fn(async () => undefined), open: vi.fn() },
    storage: {
      session: { get: vi.fn(async () => ({ sauriState: { status: "idle" } })), set: vi.fn(async () => undefined) },
      local: { get: vi.fn(async () => ({})), set: vi.fn(async () => undefined), remove: vi.fn(async () => undefined) },
    },
    tabs: { onRemoved: { addListener: vi.fn() }, onUpdated: { addListener: vi.fn() }, query, create, sendMessage: vi.fn(async () => undefined) },
  });
  let acceptedAmbiguousClaim = false;
  async function drain() {
    // fake-indexeddb transactions advance on task callbacks. Await the actual
    // durable claim/recovery rather than an arbitrary delay under parallel suites.
    const waitForLaunch = record.recordingId && !["capturing", "finalizing", "upload_pending", "uploading", "upload_failed", "upload_outcome_unavailable"].includes(record.status);
    for (let attempt = 0; waitForLaunch && attempt < 50; attempt++) {
      const saved = await getCompletion(record.sessionId);
      if ((saved?.reviewStatus ?? saved?.status) === "review_opened") break;
      if ((saved?.reviewStatus ?? saved?.status) === "review_launch_pending" && saved?.reviewCreateAttempted && crashAfterCreate) {
        if (!acceptedAmbiguousClaim || tabs.length === 0) { acceptedAmbiguousClaim = true; break; }
      }
      await new Promise(resolve => setTimeout(resolve, 10));
    }
    // Startup fire-and-forgets reconciliation; let its post-commit callbacks
    // finish before the next case unstubs IndexedDB/Chrome globals.
    await new Promise(resolve => setTimeout(resolve, 15));
  }
  async function restart() { vi.resetModules(); await import("./background"); await drain(); }
  await restart();
  return { create, query, boundaryErrors, tabs, async event(event: Event) {
    if (event === "restart") await restart();
    else { await (event === "startup" ? startup!() : alarm!({ name: "sauri-upload-check" })); await drain(); }
  } };
}

function ready(sessionId: string): RecordingCompletion {
  return { sessionId, meetingId: `meeting-${sessionId}`, recordingId: `recording-${sessionId}`,
    provider: "meet", capturedTabId: 42, status: "processing_succeeded", updatedAt: 1 };
}

afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); });

it("allows exactly one persisted claim across 100 duplicate/concurrent claim sequences", async () => {
  for (const { sessionId, events } of sequences) {
    vi.stubGlobal("indexedDB", new IDBFactory());
    await createCompletion(ready(sessionId));
    const claims = await Promise.all(events.map(() => claimReviewLaunch(sessionId)));
    expect(claims.filter(Boolean), sessionId).toHaveLength(1);
    expect(await getCompletion(sessionId)).toMatchObject({ ...ready(sessionId), reviewStatus: "review_launch_pending", updatedAt: expect.any(Number) });
    expect(await claimReviewLaunch(sessionId)).toBe(false);
  }
});

it("never claims or opens review from 100 non-ready recording sequences", async () => {
  const nonReady: RecordingCompletion["status"][] = ["capturing", "finalizing", "upload_pending", "uploading", "upload_failed", "upload_outcome_unavailable"];
  for (const [index, { sessionId, events }] of sequences.entries()) {
    const record = { ...ready(sessionId), status: nonReady[index % nonReady.length] };
    const harness = await worker(record);
    for (const event of events) await harness.event(event);
    expect(await claimReviewLaunch(sessionId), `${index}: ${record.status}`).toBe(false);
    expect(harness.create).not.toHaveBeenCalled();
    expect((await getCompletion(sessionId))?.status).not.toBe("review_opened");
  }
}, 60000);

it("opens exactly one review after verified success through 100 retry/restart sequences", async () => {
  const failures: string[] = [];
  for (const { sessionId, events } of sequences) {
    const harness = await worker(ready(sessionId));
    for (const event of events) await harness.event(event);
    const saved = await getCompletion(sessionId);
    if (harness.create.mock.calls.length !== 1 || (saved?.reviewStatus ?? saved?.status) !== "review_opened" ||
        saved?.reviewTabId !== 614 || harness.boundaryErrors.length ||
        new URL(harness.tabs[0].url).searchParams.get("meetingId") !== `meeting-${sessionId}`) {
      failures.push(`${sessionId}: creates=${harness.create.mock.calls.length}, status=${saved?.status}, boundary=${harness.boundaryErrors.join(",")}`);
    }
  }
  expect(failures, `100 executed sequences; first counterexample: ${failures[0]}`).toEqual([]);
}, 60000);

it("reconciles a pending launch with the existing exact target after interruption (100 sequences)", async () => {
  const failures: string[] = [];
  for (const { sessionId, events } of sequences) {
    const harness = await worker(ready(sessionId), true);
    for (const event of events) await harness.event(event);
    // The Chrome boundary keeps the first tab even though its result was lost.
    // Recovery must query that actual URL, not manufacture another destination.
    await harness.event("restart");
    const saved = await getCompletion(sessionId);
    if (harness.tabs.length !== 1 || !harness.query.mock.calls.length || (saved?.reviewStatus ?? saved?.status) !== "review_opened" ||
        saved?.reviewTabId !== 614 || harness.boundaryErrors.length) {
      failures.push(`${sessionId}: tabs=${harness.tabs.length}, queries=${harness.query.mock.calls.length}, status=${saved?.status}`);
    }
  }
  expect(failures, `100 executed interruption sequences; first counterexample: ${failures[0]}`).toEqual([]);
}, 60000);

it("recovers a previously pending exact target without creating a tab (100 sequences)", async () => {
  const failures: string[] = [];
  for (const { sessionId, events } of sequences) {
    const harness = await worker({ ...ready(sessionId), status: "review_launch_pending" }, false, true);
    for (const event of events) await harness.event(event);
    const saved = await getCompletion(sessionId);
    if (harness.create.mock.calls.length || (saved?.reviewStatus ?? saved?.status) !== "review_opened" ||
        saved?.reviewTabId !== 614 || !harness.query.mock.calls.length) failures.push(sessionId);
  }
  expect(failures).toEqual([]);
}, 60000);

it("never repeats an ambiguous Chrome create after its tab disappeared (100 sequences)", async () => {
  const failures: string[] = [];
  for (const { sessionId, events } of sequences) {
    const harness = await worker(ready(sessionId), true);
    harness.tabs.splice(0); // tab closed between Chrome creating it and worker recovering
    for (const event of events) await harness.event(event);
    const saved = await getCompletion(sessionId);
    if (harness.create.mock.calls.length !== 1 || (saved?.reviewStatus ?? saved?.status) !== "review_launch_pending" ||
        !saved?.reviewCreateAttempted) failures.push(sessionId);
  }
  expect(failures).toEqual([]);
}, 60000);

it("opens the uploaded meeting before processing and never reopens after success or worker restart", async () => {
  const record = { ...ready("uploaded-session"), status: "upload_succeeded" as const };
  const harness = await worker(record);
  expect(harness.create).toHaveBeenCalledTimes(1);
  expect(harness.create).toHaveBeenCalledWith({ url: "http://localhost:5173/?meetingId=meeting-uploaded-session" });
  expect(harness.boundaryErrors).toEqual([]);
  expect(await getCompletion(record.sessionId)).toMatchObject({ status: "processing_status_unavailable", reviewStatus: "review_opened" });
  // The portal normalizes its URL, and users may close it before processing ends.
  // Neither an absent nor a changed URL authorizes a second creation attempt.
  harness.tabs.splice(0);
  await setProcessingStatus(record.sessionId, record.meetingId, record.recordingId!, "processing_succeeded");
  for (const event of ["retry", "restart", "startup", "retry"] as Event[]) await harness.event(event);
  expect(harness.create).toHaveBeenCalledTimes(1);
  expect(await getCompletion(record.sessionId)).toMatchObject({ status: "processing_succeeded", reviewStatus: "review_opened" });
});

it.each(["processing", "processing_assets_unavailable", "processing_status_unavailable", "processing_failed"] as const)(
  "recovers an unclaimed upload launch from persisted %s", async status => {
    const harness = await worker({ ...ready(status), status });
    expect(harness.create).toHaveBeenCalledTimes(1);
    await harness.event("restart");
    expect(harness.create).toHaveBeenCalledTimes(1);
  },
);

it("does not launch an upload without a bound server recording ID", async () => {
  const record = { ...ready("unbound"), recordingId: undefined, status: "upload_succeeded" as const };
  const harness = await worker(record);
  await harness.event("retry");
  expect(await claimReviewLaunch(record.sessionId)).toBe(false);
  expect(harness.create).not.toHaveBeenCalled();
});

it("recovers an interrupted upload launch by exact URL without duplicating after restart", async () => {
  const record = { ...ready("interrupted-upload"), status: "upload_succeeded" as const };
  const harness = await worker(record, true);
  expect(harness.create).toHaveBeenCalledTimes(1);
  await harness.event("restart");
  expect(harness.create).toHaveBeenCalledTimes(1);
  expect(await getCompletion(record.sessionId)).toMatchObject({ reviewStatus: "review_opened", reviewTabId: 614 });
});

it("reuses the exact uploaded meeting tab instead of creating another", async () => {
  const record = { ...ready("existing-upload"), status: "upload_succeeded" as const };
  const harness = await worker(record, false, true);
  expect(harness.create).not.toHaveBeenCalled();
  expect(await getCompletion(record.sessionId)).toMatchObject({ reviewStatus: "review_opened", reviewTabId: 614 });
});
