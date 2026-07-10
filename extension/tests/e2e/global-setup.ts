import { spawn, ChildProcess } from "child_process";
import { existsSync, openSync, writeFileSync } from "fs";
import { dirname, resolve } from "path";
import { fileURLToPath } from "url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const BACKEND_DIR = resolve(__dirname, "../../../backend");
// Worktrees created by _tools/new-worktree.sh don't get a local backend/.venv
// (it's not symlinked, unlike node_modules) — fall back to $SAURI_VENV_PYTHON
// or the primary checkout's venv for local development.
const LOCAL_VENV_PYTHON = resolve(BACKEND_DIR, ".venv/bin/python");
const VENV_PYTHON =
  process.env.SAURI_VENV_PYTHON ??
  (existsSync(LOCAL_VENV_PYTHON)
    ? LOCAL_VENV_PYTHON
    : resolve(BACKEND_DIR, "../../../sauri/backend/.venv/bin/python"));
const PID_FILE = resolve(__dirname, ".backend-pid");

async function waitForHealth(url: string, attempts = 60): Promise<void> {
  for (let i = 0; i < attempts; i++) {
    try {
      const res = await fetch(url);
      if (res.ok) return;
    } catch {
      // not up yet
    }
    await new Promise((r) => setTimeout(r, 500));
  }
  throw new Error(`Backend at ${url} did not become healthy in time`);
}

export default async function globalSetup(): Promise<void> {
  const env = {
    ...process.env,
    DATABASE_URL: "postgresql+asyncpg://sauri:sauri_dev@localhost:5432/sauri",
    OBJECT_STORE_ENDPOINT: "http://localhost:9000",
    OBJECT_STORE_BUCKET: "sauri-recordings-e2e",
    MINIO_ROOT_USER: "minioadmin",
    MINIO_ROOT_PASSWORD: "minioadmin",
    QUEUE_BROKER_URL: "amqp://guest:guest@localhost:5672/",
    AUTH_DISABLED: "true",
    ASR_PROVIDER: "local",
    ASR_LOCAL_URL: "http://127.0.0.1:9/unused",
  };

  // Create the MinIO bucket and the DB schema before starting the API.
  const setupScript = `
import asyncio
import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

async def main():
    import app.infra.models  # noqa: F401 — registers all tables on Base.metadata
    from app.infra.database import Base
    from sqlalchemy.ext.asyncio import create_async_engine

    engine = create_async_engine("${env.DATABASE_URL}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await engine.dispose()

    client = boto3.client(
        "s3",
        endpoint_url="${env.OBJECT_STORE_ENDPOINT}",
        aws_access_key_id="${env.MINIO_ROOT_USER}",
        aws_secret_access_key="${env.MINIO_ROOT_PASSWORD}",
        config=Config(signature_version="s3v4"),
    )
    try:
        client.create_bucket(Bucket="${env.OBJECT_STORE_BUCKET}")
    except ClientError:
        pass

asyncio.run(main())
`;

  await new Promise<void>((resolvePromise, reject) => {
    const proc = spawn(VENV_PYTHON, ["-c", setupScript], {
      cwd: BACKEND_DIR,
      env,
    });
    let stderr = "";
    proc.stderr?.on("data", (d) => (stderr += d.toString()));
    proc.on("exit", (code) => {
      if (code === 0) resolvePromise();
      else reject(new Error(`Setup script failed (${code}): ${stderr}`));
    });
  });

  const logFile = resolve(__dirname, ".backend.log");
  const logFd = openSync(logFile, "w");
  const backend: ChildProcess = spawn(
    VENV_PYTHON,
    ["-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8000"],
    {
      cwd: BACKEND_DIR,
      env,
      stdio: ["ignore", logFd, logFd],
      detached: true,
    }
  );
  backend.unref();

  writeFileSync(PID_FILE, String(backend.pid));

  await waitForHealth("http://127.0.0.1:8000/health");
}
