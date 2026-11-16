/** T3.1 #627/#628: synthetic handles through real MV3 listeners, upload, protected API and portal.
 * Media/Chrome provider capture and worker completion are the only simulated boundaries.
 * No live meeting, owner DB/bucket, bypassed auth, or fake protected API response.
 */
import { test, expect, chromium, type BrowserContext, type Page } from "@playwright/test";
import { execFileSync } from "node:child_process";
import { mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const extensionPath = resolve(here, "../../dist");
const backendDir = resolve(here, "../../../backend");
const media = [...readFileSync(resolve(here, "../../src/fixtures/synthetic-av.webm"))];
const backend = () => process.env.SAURI_E2E_BACKEND_URL!;
const portal = () => process.env.SAURI_E2E_PORTAL_URL!;

type Completion = { sessionId: string; meetingId: string; recordingId?: string; status: string; trigger?: string };
async function login(email = "owner@synthetic.invalid"): Promise<string> {
  const response = await fetch(`${backend()}/api/v1/auth/login`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password: "synthetic-only-password" }),
  });
  expect(response.status).toBe(200);
  return (await response.json()).access_token as string;
}
async function protectedRead(meetingId: string, token?: string, suffix = "") {
  return fetch(`${backend()}/api/v1/meetings/${meetingId}${suffix}`,
    token ? { headers: { Authorization: `Bearer ${token}` } } : undefined);
}
function finishProcessing(meetingId: string, outcome: "complete" | "failed" | "unavailable" | "assets" = "complete") {
  const stdout = execFileSync(process.env.SAURI_E2E_PYTHON!, [resolve(here, "fixture.py"), outcome, meetingId],
    { cwd: backendDir, env: process.env, encoding: "utf8" });
  return outcome !== "failed" ? JSON.parse(stdout) as { recording_id: string; meeting_id: string; session_id: string; audio_ref: string } : null;
}
async function completion(page: Page, sessionId: string): Promise<Completion | undefined> {
  return page.evaluate(async sessionId => {
    const db = await new Promise<IDBDatabase>((resolve, reject) => {
      const request = indexedDB.open("sauri-recordings", 2);
      request.onsuccess = () => resolve(request.result);
      request.onerror = () => reject(request.error);
    });
    try {
      return await new Promise<Completion | undefined>((resolve, reject) => {
        const request = db.transaction("completion_records").objectStore("completion_records").get(sessionId);
        request.onsuccess = () => resolve(request.result as Completion | undefined);
        request.onerror = () => reject(request.error);
      });
    } finally { db.close(); }
  }, sessionId);
}
async function seedHandle(page: Page, tabId: number, provider: "meet" | "teams") {
  const sessionId = crypto.randomUUID();
  const meetingId = crypto.randomUUID();
  await page.evaluate(async ({ sessionId, meetingId, tabId, provider, media }) => {
    const database = await new Promise<IDBDatabase>((resolve, reject) => {
      const request = indexedDB.open("sauri-recordings", 2);
      request.onupgradeneeded = () => {
        const chunks = request.result.createObjectStore("chunks", { keyPath: "id", autoIncrement: true });
        chunks.createIndex("by_session", "sessionId");
        const records = request.result.createObjectStore("completion_records", { keyPath: "sessionId" });
        records.createIndex("capturedTabId", "capturedTabId");
      };
      request.onsuccess = () => resolve(request.result);
      request.onerror = () => reject(request.error);
    });
    await new Promise<void>((resolve, reject) => {
      const tx = database.transaction(["completion_records", "chunks"], "readwrite");
      tx.objectStore("completion_records").add({ sessionId, meetingId, provider, capturedTabId: tabId,
        status: "capturing", updatedAt: Date.now() });
      tx.objectStore("chunks").add({ sessionId, blob: new Blob([new Uint8Array(media)], { type: "video/webm" }), timestamp: Date.now() });
      tx.oncomplete = () => resolve();
      tx.onabort = () => reject(tx.error);
    });
    database.close();
    await chrome.storage.session.set({ sauriState: { status: "recording", sessionId, tabId, provider,
      meetingTitle: `Synthetic ${provider}`, meetingUrl: `https://${provider === "meet" ? "meet.google.com" : "teams.microsoft.com"}/synthetic`,
      videoPresence: "muxed" } });
  }, { sessionId, meetingId, tabId, provider, media });
  return { sessionId, meetingId };
}
async function extensionSession(context: BrowserContext) {
  const worker = context.serviceWorkers()[0] ?? await context.waitForEvent("serviceworker");
  const id = new URL(worker.url()).host;
  const panel = await context.newPage();
  await panel.goto(`chrome-extension://${id}/src/panel/index.html`);
  return { worker, panel };
}
async function mediaMessage(panel: Page, payload: { type: string; sessionId?: string; size?: number; mimeType?: string }) {
  return panel.evaluate(payload => new Promise<{ ok: boolean }>((resolve, reject) => {
    const port = chrome.runtime.connect({ name: "e2e-media-owner" });
    const timeout = setTimeout(() => { port.disconnect(); reject(new Error("Offscreen fixture did not respond")); }, 5000);
    port.onMessage.addListener(message => {
      if (message.id !== 1) return;
      clearTimeout(timeout);
      port.disconnect();
      if (message.error) reject(new Error(message.error));
      else resolve(message.response);
    });
    port.postMessage({ id: 1, payload });
  }), payload);
}
async function reviewTabs(context: BrowserContext, meetingId: string) {
  return context.pages().filter(page => page.url() === `${portal()}/?meetingId=${meetingId}`);
}

for (const [provider, outcome] of [["meet", "ready"], ["teams", "ready"],
  ["meet", "failed"], ["teams", "unavailable"], ["meet", "upload_failed"]] as const) {
  test(`${provider}: ${outcome} synthetic completion and protected review gate`, async ({}, testInfo) => {
    const profile = mkdtempSync(resolve(tmpdir(), "sauri-e2e-profile-"));
    const context = await chromium.launchPersistentContext(profile, {
      channel: "chromium", headless: true,
      args: [`--disable-extensions-except=${extensionPath}`, `--load-extension=${extensionPath}`],
    });
    try {
      const token = await login();
      const other = await login("other@synthetic.invalid");
      const { worker, panel } = await extensionSession(context);
      await panel.evaluate(token => chrome.storage.session.set({ sauriSessionToken: token }),
        outcome === "upload_failed" ? "invalid-synthetic-token" : token);
      // A synthetic provider page supplies only a captured tab handle. No Teams capture pipeline.
      const providerPage = await context.newPage();
      const providerUrl = provider === "meet" ? "https://meet.google.com/e2e-synthetic" : "https://teams.microsoft.com/e2e-synthetic";
      await context.route(`${providerUrl}**`, route => route.fulfill({ status: 200, contentType: "text/html",
        body: `<html><head><title>Synthetic ${provider}</title></head><body>synthetic handle</body></html>` }));
      await providerPage.goto(providerUrl);
      const capturedTabId = await panel.evaluate(async url => {
        const tabs = await chrome.tabs.query({});
        return tabs.find(tab => tab.url === url)?.id;
      }, providerUrl);
      expect(capturedTabId).toBeDefined();
      const { sessionId, meetingId } = await seedHandle(panel, capturedTabId!, provider);
      // Synthetic offscreen media owner: the real background Stop/close listener and upload queue execute.
      await worker.evaluate(() => chrome.offscreen.createDocument({ url: "src/e2e/fixture.html",
        reasons: [chrome.offscreen.Reason.USER_MEDIA], justification: "Synthetic E2E media boundary" }));
      if (provider === "meet") {
        await panel.evaluate(() => chrome.runtime.sendMessage({ type: "meet-ended" }));
        expect((await completion(panel, sessionId))?.status).toBe("capturing");
        await providerPage.close();
      } else {
        const result = await mediaMessage(panel, { type: "stop-capture" });
        expect(result.ok).toBe(true);
        await providerPage.close(); // duplicate completion attempt
      }
      await expect.poll(async () => (await completion(panel, sessionId))?.status).toBe("finalizing");
      await mediaMessage(panel, { type: "recording-stopped", sessionId, size: 3043, mimeType: "video/webm" });
      if (outcome === "upload_failed") {
        await expect.poll(async () => (await completion(panel, sessionId))?.status).toBe("upload_failed");
        expect((await completion(panel, sessionId))?.recordingId).toBeUndefined();
        expect((await protectedRead(meetingId, token)).status).toBe(404);
        expect(await reviewTabs(context, meetingId)).toHaveLength(0);
        return;
      }
      try {
        await expect.poll(async () => (await completion(panel, sessionId))?.recordingId, { timeout: 30_000 }).toBeTruthy();
      } catch (error) {
        console.log("[completion]", await completion(panel, sessionId));
        console.log("[backend]", readFileSync(process.env.SAURI_E2E_BACKEND_LOG!, "utf8").slice(-4500));
        throw error;
      }
      const uploaded = await completion(panel, sessionId);
      expect(uploaded?.meetingId).toBe(meetingId);
      expect((await protectedRead(meetingId)).status).toBe(401);
      expect((await protectedRead(meetingId, other)).status).toBe(404);
      for (const asset of ["/transcript", "/playback"]) {
        expect((await protectedRead(meetingId, undefined, asset)).status).toBe(401);
        expect((await protectedRead(meetingId, other, asset)).status).toBe(404);
      }
      const confirmed = await protectedRead(meetingId, token);
      expect(confirmed.status).toBe(200);
      expect((await confirmed.json()).recording_id).toBe(uploaded?.recordingId);
      expect(await reviewTabs(context, meetingId)).toHaveLength(0);
      await mediaMessage(panel, { type: "recording-stopped", sessionId, size: 3043, mimeType: "video/webm" });
      expect((await completion(panel, sessionId))?.recordingId).toBe(uploaded?.recordingId);
      if (outcome === "failed") {
        finishProcessing(meetingId, "failed");
        await worker.evaluate(() => chrome.alarms.create("sauri-upload-check", { when: Date.now() + 100 }));
        await expect.poll(async () => (await completion(panel, sessionId))?.status).toBe("processing_failed");
        expect(await reviewTabs(context, meetingId)).toHaveLength(0);
        return;
      }
      const processing = finishProcessing(meetingId, "unavailable");
      expect(processing?.session_id).toBe(sessionId);
      expect(processing?.recording_id).toBe(uploaded?.recordingId);
      await worker.evaluate(() => chrome.alarms.create("sauri-upload-check", { when: Date.now() + 100 }));
      await expect.poll(async () => (await completion(panel, sessionId))?.status).toBe("processing_assets_unavailable");
      expect(await reviewTabs(context, meetingId)).toHaveLength(0);
      if (outcome === "unavailable") return;
      // Terminate the actual MV3 worker target; reloading the panel must recover
      // the durable unavailable projection before its next authenticated poll.
      const cdp = await context.newCDPSession(panel);
      const targets = await cdp.send("Target.getTargets");
      const workerTarget = targets.targetInfos.find((target: { type: string; url: string }) =>
        target.type === "service_worker" && target.url.startsWith("chrome-extension://"));
      expect(workerTarget).toBeDefined();
      await cdp.send("Target.closeTarget", { targetId: workerTarget!.targetId });
      await cdp.detach();
      await panel.reload();
      await expect(panel.getByText("Processing assets unavailable")).toBeVisible();
      finishProcessing(meetingId, "assets");
      // Real object-store URL and protected assets, not a mocked ready status.
      const transcriptResponse = await protectedRead(meetingId, token, "/transcript");
      expect(transcriptResponse.status).toBe(200);
      expect((await transcriptResponse.json()).meeting_id).toBe(meetingId);
      const playbackResponse = await protectedRead(meetingId, token, "/playback");
      expect(playbackResponse.status).toBe(200);
      const playback = await playbackResponse.json();
      expect(playback.meeting_id).toBe(meetingId);
      expect(playback.muxed_video_source.url).toContain(processing?.audio_ref);
      const storedMedia = await fetch(playback.muxed_video_source.url);
      expect(storedMedia.status).toBe(200);
      expect([...new Uint8Array(await storedMedia.arrayBuffer())]).toEqual(media);
      await panel.evaluate(() => chrome.runtime.sendMessage({ type: "teams-ended" }));
      const recoveredWorker = context.serviceWorkers()[0] ?? await context.waitForEvent("serviceworker");
      await recoveredWorker.evaluate(() => chrome.alarms.create("sauri-upload-check", { when: Date.now() + 100 }));
      await expect.poll(async () => (await reviewTabs(context, meetingId)).length, { timeout: 20_000 }).toBe(1);
      const review = (await reviewTabs(context, meetingId))[0];
      await expect(review.getByText("Log in", { exact: false }).first()).toBeVisible();
      // The portal itself logs in against the real backend and loads the same protected assets.
      await review.getByLabel(/email/i).fill("owner@synthetic.invalid");
      await review.getByLabel(/password/i).fill("synthetic-only-password");
      await review.getByRole("button", { name: /log in|sign in/i }).click();
      await expect(review.getByText("Log out")).toBeVisible();
      await expect(review.getByRole("region", { name: "Meeting playback" })).toBeVisible();
      await expect(review.getByText("Provider: synthetic-e2e")).toBeVisible();
      if (provider === "meet") await review.screenshot({ path: testInfo.outputPath("authenticated-review.png") });
      await panel.reload();
      await expect.poll(async () => (await completion(panel, sessionId))?.status).toBe("review_opened");
      await expect(panel.getByText("Review opened")).toBeVisible();
      await panel.evaluate(() => chrome.alarms.create("sauri-upload-check", { when: Date.now() + 100 }));
      await expect.poll(async () => (await reviewTabs(context, meetingId)).length).toBe(1);
    } finally {
      await context.close();
      rmSync(profile, { recursive: true, force: true });
    }
  });
}
