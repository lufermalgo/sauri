import { execFileSync, spawn, type ChildProcess } from "node:child_process";
import { randomBytes, randomUUID } from "node:crypto";
import { existsSync, mkdtempSync, rmSync, openSync, closeSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, resolve } from "node:path";
import { createServer } from "node:net";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const root = resolve(here, "../../..");
const backend = resolve(root, "backend");
const extension = resolve(root, "extension");
const frontend = resolve(root, "frontend");
const run = `sauri-e2e-${randomUUID().replaceAll("-", "").slice(0, 16)}`;
const names = ["postgres", "object", "queue"].map(service => `${run}-${service}`);
const volumes = [`${run}-pg`, `${run}-objects`];
const network = run;
const temp = mkdtempSync(resolve(tmpdir(), "sauri-e2e-"));
const children: ChildProcess[] = [];

function docker(...args: string[]): string {
  return execFileSync("docker", args, { encoding: "utf8", timeout: 60_000, stdio: ["ignore", "pipe", "pipe"] }).trim();
}
function availablePython(): string {
  const candidates = [process.env.SAURI_VENV_PYTHON, resolve(backend, ".venv/bin/python"),
    resolve(root, "../../backend/.venv/bin/python")];
  for (const python of candidates) {
    if (!python || !existsSync(python)) continue;
    try {
      execFileSync(python, ["-c", "import sys, fastapi, sqlalchemy, boto3; assert sys.prefix != sys.base_prefix"],
        { timeout: 10_000 });
      return python;
    } catch { /* Try another valid virtualenv, never system Python. */ }
  }
  throw new Error("Set SAURI_VENV_PYTHON to a backend venv with FastAPI, SQLAlchemy and boto3");
}
function mappedPort(name: string, port: number): number {
  const mapping = docker("port", name, `${port}/tcp`).split("\n")[0];
  const value = Number(mapping.slice(mapping.lastIndexOf(":") + 1));
  if (!Number.isInteger(value) || value < 1) throw new Error(`Missing isolated port for ${name}:${port}`);
  return value;
}
async function freePort(): Promise<number> {
  const server = createServer();
  await new Promise<void>(resolve => server.listen(0, "127.0.0.1", resolve));
  const address = server.address();
  if (!address || typeof address === "string") throw new Error("No local port");
  await new Promise<void>(resolve => server.close(() => resolve()));
  return address.port;
}
async function waitFor(url: string, attempts = 100): Promise<void> {
  for (let attempt = 0; attempt < attempts; attempt++) {
    try { if ((await fetch(url)).ok) return; } catch { /* Not ready yet. */ }
    await new Promise(resolve => setTimeout(resolve, 400));
  }
  throw new Error(`Isolated service unavailable at ${url}`);
}
async function waitForPython(python: string, env: NodeJS.ProcessEnv): Promise<void> {
  for (let attempt = 0; attempt < 100; attempt++) {
    try {
      execFileSync(python, ["-c", "import asyncio; from app.infra.database import create_engine; from sqlalchemy import text\nasync def check():\n e=create_engine()\n async with e.connect() as c: await c.execute(text('select 1'))\n await e.dispose()\nasyncio.run(check())"],
        { cwd: backend, env, stdio: "pipe", timeout: 3000 });
      return;
    } catch { await new Promise(resolve => setTimeout(resolve, 400)); }
  }
  throw new Error("Isolated PostgreSQL did not become ready");
}
function stop(): void {
  for (const child of children) child.kill("SIGTERM");
  for (const name of names) { try { docker("rm", "-f", name); } catch { /* May not have started. */ } }
  for (const volume of volumes) { try { docker("volume", "rm", volume); } catch { /* May not exist. */ } }
  try { docker("network", "rm", network); } catch { /* May not exist. */ }
  rmSync(temp, { recursive: true, force: true });
  const leaked = [...names.map(name => ["container", name] as const),
    ...volumes.map(name => ["volume", name] as const), ["network", network] as const]
    .filter(([kind, name]) => {
      try { docker(...(kind === "container" ? ["inspect", name] : [kind, "inspect", name])); return true; }
      catch { return false; }
    });
  if (leaked.length) throw new Error(`Isolated Docker resources not removed: ${JSON.stringify(leaked)}`);
}

export default async function globalSetup(): Promise<() => void> {
  try {
    const python = availablePython();
    docker("network", "create", network);
    for (const volume of volumes) docker("volume", "create", volume);
    docker("run", "-d", "--rm", "--name", names[0], "--network", network,
      "-p", "127.0.0.1::5432", "-v", `${volumes[0]}:/var/lib/postgresql/data`,
      "-e", "POSTGRES_DB=sauri_e2e", "-e", "POSTGRES_USER=e2e", "-e", "POSTGRES_PASSWORD=e2e_only", "postgres:16");
    docker("run", "-d", "--rm", "--name", names[1], "--network", network,
      "-p", "127.0.0.1::9000", "-v", `${volumes[1]}:/data`,
      "-e", "MINIO_ROOT_USER=e2e_minio", "-e", "MINIO_ROOT_PASSWORD=e2e_secret_only",
      "rustfs/rustfs@sha256:9ca9559533b537d10482fe923288b676ad08f92a7069d9a17327fbae3cab688b",
      "server", "/data");
    docker("run", "-d", "--rm", "--name", names[2], "--network", network,
      "-p", "127.0.0.1::5672", "-e", "RABBITMQ_DEFAULT_USER=e2e", "-e", "RABBITMQ_DEFAULT_PASS=e2e_only", "rabbitmq:3-management");
    const dbPort = mappedPort(names[0], 5432);
    const objectPort = mappedPort(names[1], 9000);
    const queuePort = mappedPort(names[2], 5672);
    const backendPort = await freePort();
    const frontendPort = await freePort();
    const env = {
      ...process.env, PYTHONPATH: backend, DATABASE_URL: `postgresql+asyncpg://e2e:e2e_only@127.0.0.1:${dbPort}/sauri_e2e`,
      OBJECT_STORE_ENDPOINT: `http://127.0.0.1:${objectPort}`, OBJECT_STORE_BUCKET: `${run}-bucket`,
      MINIO_ROOT_USER: "e2e_minio", MINIO_ROOT_PASSWORD: "e2e_secret_only",
      QUEUE_BROKER_URL: `amqp://e2e:e2e_only@127.0.0.1:${queuePort}/`,
      QUEUE_MESSAGE_SIGNING_KEY: randomBytes(32).toString("hex"), JWT_SECRET: randomBytes(32).toString("hex"),
      SPEAKER_EXCERPT_ACTIVE_KEY_ID: "e2e", SPEAKER_EXCERPT_KEYRING: `e2e:${randomBytes(32).toString("base64url")}`,
      AUTH_DISABLED: "false", APP_ENV: "test", ASR_PROVIDER: "local",
      SAURI_E2E_RUN_ID: run, SAURI_E2E_PYTHON: python, SAURI_E2E_BACKEND_URL: `http://localhost:${backendPort}`,
      SAURI_E2E_PORTAL_URL: `http://localhost:${frontendPort}`,
    };
    // Never inherit a developer's public object-store endpoint into signed media URLs.
    delete env.OBJECT_STORE_PUBLIC_ENDPOINT;
    await waitForPython(python, env);
    // Seed only synthetic identities in the freshly created, uniquely named database.
    execFileSync(python, [resolve(here, "fixture.py"), "init"], { cwd: backend, env, timeout: 30_000 });
    const log = resolve(temp, "backend.log");
    process.env.SAURI_E2E_BACKEND_LOG = log;
    const logFd = openSync(log, "w");
    const backendProcess = spawn(python, ["-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", String(backendPort)],
      { cwd: backend, env, stdio: ["ignore", logFd, logFd] });
    closeSync(logFd);
    children.push(backendProcess);
    await waitFor(`${env.SAURI_E2E_BACKEND_URL}/health`);
    execFileSync("npm", ["run", "build"], { cwd: extension, env: {
      ...env, SAURI_E2E_BUILD: "1", VITE_SAURI_BACKEND_URL: env.SAURI_E2E_BACKEND_URL, VITE_SAURI_PORTAL_URL: env.SAURI_E2E_PORTAL_URL,
    }, stdio: "pipe", timeout: 120_000 });
    const frontendProcess = spawn(resolve(root, "node_modules/.bin/vite"),
      ["--host", "127.0.0.1", "--port", String(frontendPort), "--strictPort"],
      { cwd: frontend, env: { ...env, VITE_API_BASE_URL: env.SAURI_E2E_BACKEND_URL } });
    children.push(frontendProcess);
    await waitFor(env.SAURI_E2E_PORTAL_URL);
    for (const [key, value] of Object.entries(env)) if (key.startsWith("SAURI_E2E_") || key === "DATABASE_URL" || key === "PYTHONPATH") process.env[key] = value;
    return stop;
  } catch (error) {
    stop();
    throw error;
  }
}
