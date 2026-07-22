/**
 * E2E: extension load, mocked Meet detection, capture -> ingestion.
 *
 * Feature: meeting-capture-transcription
 * Task: 17.4 — Validates: Requirements 2.1, 2.2
 *
 * chrome.tabCapture requires a real user gesture and OS screen capture,
 * which can't be reliably automated in a headless CI environment (this is a
 * known Chrome limitation, not a test limitation). So this test drives the
 * flow from the point where the offscreen document would already have
 * produced a recording — invoking the real "recording-stopped" message from
 * an extension page (the standard page->background pattern, same as the
 * real panel) — and verifies end-to-end the rest of the real pipeline: Meet
 * detection, upload queue, real multipart upload to the backend, and the
 * Meeting's transition to "transcribing".
 */

import { test, expect, chromium, type BrowserContext } from "@playwright/test";
import { execFile } from "child_process";
import { existsSync } from "fs";
import { dirname, resolve } from "path";
import { fileURLToPath } from "url";
import { promisify } from "util";

const execFileAsync = promisify(execFile);

const __dirname = dirname(fileURLToPath(import.meta.url));
const EXTENSION_PATH = resolve(__dirname, "../../dist");
const BACKEND_URL = "http://127.0.0.1:8000";
const BACKEND_DIR = resolve(__dirname, "../../../backend");
const LOCAL_VENV_PYTHON = resolve(BACKEND_DIR, ".venv/bin/python");
const VENV_PYTHON =
  process.env.SAURI_VENV_PYTHON ??
  (existsSync(LOCAL_VENV_PYTHON)
    ? LOCAL_VENV_PYTHON
    : resolve(BACKEND_DIR, "../../../sauri/backend/.venv/bin/python"));

/**
 * The Meeting auto-created by ingestion (real extension flow) has
 * created_by="extension" and so does NOT appear in GET /api/v1/meetings/
 * (filtered by the authenticated user) — it's queried directly against
 * Postgres to identify it, since get_meeting (GET /{id}) does work without
 * that filter but requires knowing the id beforehand.
 */
async function meetingsCreatedByExtension(): Promise<string[]> {
  const script = `
import asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
import app.infra.models as models

async def main():
    engine = create_async_engine("postgresql+asyncpg://sauri:sauri_dev@localhost:5432/sauri")
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with session_factory() as session:
        result = await session.execute(
            select(models.Meeting.id).where(models.Meeting.created_by == "extension")
        )
        for row in result.scalars().all():
            print(row)
    await engine.dispose()

asyncio.run(main())
`;
  const { stdout } = await execFileAsync(VENV_PYTHON, ["-c", script], { cwd: BACKEND_DIR });
  return stdout.split("\n").map((s) => s.trim()).filter(Boolean);
}

const FAKE_MEET_HTML = `
<!doctype html>
<html>
  <head><title>Test Meeting - Google Meet</title></head>
  <body>
    <button aria-label="Leave call">Leave</button>
    <button aria-label="Turn off microphone">Mic</button>
  </body>
</html>
`;

async function launchWithExtension(): Promise<BrowserContext> {
  return chromium.launchPersistentContext("", {
    headless: false,
    args: [
      `--disable-extensions-except=${EXTENSION_PATH}`,
      `--load-extension=${EXTENSION_PATH}`,
    ],
  });
}

async function getExtensionId(context: BrowserContext): Promise<string> {
  let [sw] = context.serviceWorkers();
  if (!sw) {
    sw = await context.waitForEvent("serviceworker", { timeout: 15_000 });
  }
  return sw.url().split("/")[2];
}

test("capture -> ingestion: detects mocked Meet, uploads to the backend, and transitions to transcribing", async () => {
  const context = await launchWithExtension();

  try {
    const extensionId = await getExtensionId(context);
    expect(extensionId).toBeTruthy();

    const [sw] = context.serviceWorkers();
    sw?.on("console", (msg) => console.log("[SW]", msg.text()));

    // Extension's own page: standard context for talking to the background
    // via chrome.runtime.sendMessage (same as the real panel).
    const extPage = await context.newPage();
    await extPage.goto(`chrome-extension://${extensionId}/src/panel/index.html`);

    // --- 1. Mocked Meet detection ---
    await context.route("https://meet.google.com/**", (route) =>
      route.fulfill({ status: 200, contentType: "text/html", body: FAKE_MEET_HTML })
    );

    const meetPage = await context.newPage();
    await meetPage.goto("https://meet.google.com/abc-defg-hij");

    await expect
      .poll(
        async () =>
          extPage.evaluate(async () => {
            const result = await chrome.storage.session.get("sauriState");
            return (result.sauriState as { status: string } | undefined)?.status;
          }),
        { timeout: 10_000 }
      )
      .toBe("pending");

    // --- 2. Simulate the end of a real recording (offscreen would already
    //     have assembled the final Blob) and invoke the real upload flow ---
    // Note the meetings that exist before uploading, to later identify the
    // one created by this upload (background.ts generates its own
    // meeting_id (PoC) when building the payload, so it isn't known ahead
    // of time).
    const meetingsBefore = await meetingsCreatedByExtension();

    const sessionId = await extPage.evaluate(async () => crypto.randomUUID());

    // Store a test chunk in the shared IndexedDB (same DB the offscreen
    // document uses), so assembleBlob(sessionId) has content.
    await extPage.evaluate(async ({ sessionId }: { sessionId: string }) => {
      const DB_NAME = "sauri-recordings";
      const STORE_NAME = "chunks";
      const db: IDBDatabase = await new Promise((resolvePromise, reject) => {
        const req = indexedDB.open(DB_NAME, 1);
        req.onupgradeneeded = () => {
          const database = req.result;
          if (!database.objectStoreNames.contains(STORE_NAME)) {
            const store = database.createObjectStore(STORE_NAME, {
              keyPath: "id",
              autoIncrement: true,
            });
            store.createIndex("by_session", "sessionId", { unique: false });
          }
        };
        req.onsuccess = () => resolvePromise(req.result);
        req.onerror = () => reject(req.error);
      });

      await new Promise<void>((resolvePromise, reject) => {
        const tx = db.transaction(STORE_NAME, "readwrite");
        tx.objectStore(STORE_NAME).add({
          sessionId,
          blob: new Blob(["simulated-audio-content"], { type: "audio/webm" }),
          timestamp: Date.now(),
        });
        tx.oncomplete = () => resolvePromise();
        tx.onerror = () => reject(tx.error);
      });
      db.close();
    }, { sessionId });

    // Fire the real message the offscreen document sends when it finishes
    // recording (standard page->background pattern; the MV3 service worker
    // wakes up automatically to handle it).
    await extPage.evaluate(async ({ sessionId }: { sessionId: string }) => {
      await chrome.runtime.sendMessage({
        type: "recording-stopped",
        sessionId,
        size: 1024,
        mimeType: "audio/webm",
      });
    }, { sessionId });

    // --- 3. Verify against the real backend that the upload arrived (new
    //     Meeting created by ingestion) and that it transitioned to
    //     "transcribing" ---
    let meetingId: string | null = null;
    await expect
      .poll(
        async () => {
          const meetingsAfter = await meetingsCreatedByExtension();
          meetingId = meetingsAfter.find((id) => !meetingsBefore.includes(id)) ?? null;
          return meetingId;
        },
        { timeout: 10_000, message: "waiting for ingestion to create the Meeting" }
      )
      .not.toBeNull();

    await expect
      .poll(
        async () => {
          const res = await fetch(`${BACKEND_URL}/api/v1/meetings/${meetingId}`);
          if (!res.ok) return null;
          const body = await res.json();
          return body.process_state as string;
        },
        { timeout: 15_000, message: "waiting for the transition to 'transcribing'" }
      )
      .toBe("transcribing");
  } finally {
    await context.close();
  }
});
