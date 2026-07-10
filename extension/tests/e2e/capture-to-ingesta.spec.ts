/**
 * E2E: carga de la extensión, detección de Meet mockeado, captura → ingesta.
 *
 * Feature: meeting-capture-transcription
 * Task: 17.4 — Validates: Requirements 2.1, 2.2
 *
 * chrome.tabCapture requiere un gesto de usuario real y captura de pantalla del
 * SO, que no es automatizable de forma fiable en un entorno headless de CI (esto
 * es una limitación conocida de Chrome, no del test). Por eso este test dirige el
 * flujo desde el punto en que el documento offscreen ya habría producido una
 * grabación — invocando el mensaje real "recording-stopped" desde una página de
 * la propia extensión (el patrón estándar página→background, igual que hace el
 * panel real) — y verifica de extremo a extremo el resto del pipeline real:
 * detección de Meet, cola de subida, subida multipart al backend real, y
 * transición de la Reunion a "transcribiendo".
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
 * La Reunion auto-creada por la ingesta (flujo real de la extensión) tiene
 * creada_por="extension" y por eso NO aparece en GET /api/v1/reuniones/
 * (filtrado por el usuario autenticado) — se consulta directo en Postgres
 * para identificarla, ya que consultar_reunion (GET /{id}) sí funciona sin
 * ese filtro pero requiere conocer el id de antemano.
 */
async function reunionesCreadasPorExtension(): Promise<string[]> {
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
            select(models.Reunion.id).where(models.Reunion.creada_por == "extension")
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
  <head><title>Reunión de prueba - Google Meet</title></head>
  <body>
    <button aria-label="Leave call">Salir</button>
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

test("captura → ingesta: detecta Meet mockeado, sube al backend y transiciona a transcribiendo", async () => {
  const context = await launchWithExtension();

  try {
    const extensionId = await getExtensionId(context);
    expect(extensionId).toBeTruthy();

    const [sw] = context.serviceWorkers();
    sw?.on("console", (msg) => console.log("[SW]", msg.text()));

    // Página propia de la extensión: contexto estándar para hablar con el
    // background vía chrome.runtime.sendMessage (igual que el panel real).
    const extPage = await context.newPage();
    await extPage.goto(`chrome-extension://${extensionId}/src/panel/index.html`);

    // --- 1. Detección de Meet mockeado ---
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

    // --- 2. Simula el fin de una grabación real (offscreen ya habría
    //     ensamblado el Blob final) e invoca el flujo real de subida ---
    // Toma nota de las reuniones existentes antes de subir, para poder
    // identificar la que crea esta subida (background.ts genera su propio
    // reunion_id (PoC) al construir el payload, así que no se conoce de antemano).
    const reunionesAntes = await reunionesCreadasPorExtension();

    const sessionId = await extPage.evaluate(async () => crypto.randomUUID());

    // Guarda un chunk de prueba en el IndexedDB compartido (misma DB que usa
    // el documento offscreen), para que assembleBlob(sessionId) tenga contenido.
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
          blob: new Blob(["contenido-de-audio-simulado"], { type: "audio/webm" }),
          timestamp: Date.now(),
        });
        tx.oncomplete = () => resolvePromise();
        tx.onerror = () => reject(tx.error);
      });
      db.close();
    }, { sessionId });

    // Dispara el mensaje real que el offscreen envía al terminar de grabar
    // (patrón estándar página→background; el service worker MV3 se despierta
    // automáticamente para atenderlo).
    await extPage.evaluate(async ({ sessionId }: { sessionId: string }) => {
      await chrome.runtime.sendMessage({
        type: "recording-stopped",
        sessionId,
        size: 1024,
        mimeType: "audio/webm",
      });
    }, { sessionId });

    // --- 3. Verifica en el backend real que la subida llegó (nueva Reunion
    //     creada por la ingesta) y que transicionó a "transcribiendo" ---
    let reunionId: string | null = null;
    await expect
      .poll(
        async () => {
          const reunionesAhora = await reunionesCreadasPorExtension();
          reunionId = reunionesAhora.find((id) => !reunionesAntes.includes(id)) ?? null;
          return reunionId;
        },
        { timeout: 10_000, message: "esperando que la ingesta cree la Reunion" }
      )
      .not.toBeNull();

    await expect
      .poll(
        async () => {
          const res = await fetch(`${BACKEND_URL}/api/v1/reuniones/${reunionId}`);
          if (!res.ok) return null;
          const body = await res.json();
          return body.estado_proceso as string;
        },
        { timeout: 15_000, message: "esperando transición a 'transcribiendo'" }
      )
      .toBe("transcribiendo");
  } finally {
    await context.close();
  }
});
