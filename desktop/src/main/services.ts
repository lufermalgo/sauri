// What runs, in which order, and with which environment (design component 1 table and startup diagram):
// PostgreSQL on a private socket, migrations, the API (with the portal), the worker, then the engines.
import { spawn } from "node:child_process";
import { createHash, randomBytes } from "node:crypto";
import { EventEmitter } from "node:events";
import fs from "node:fs";
import path from "node:path";
import { type AppPaths, ensurePrivateDir, pgDataDir, socketPath, type UserFolders } from "./paths.ts";
import type { PortPlan } from "./ports.ts";
import { loopbackDownloadEnv, releasesRepo } from "./releases.ts";
import { commandHealth, httpHealth, RotatingLog, type ServiceSpec, Supervisor } from "./supervisor.ts";

/** PostgreSQL listens on no TCP port; the number only names its socket file. */
export const PG_SOCKET_PORT = 5432;
export const DB_USER = "sauri";
export const DB_NAME = "sauri";
/**
 * The only Chrome extensions the local API pairs with (passed as SAURI_EXTENSION_ORIGINS).
 * Any other copy gets `extension_not_allowed` and the side panel says so. To allow the
 * Chrome Web Store build, add its 32-letter id here once the store assigns it (U10).
 */
export const ALLOWED_EXTENSION_IDS = [
  "ilnkkojmkfnbdilogldabpodoobfigce", // Owner's unpacked build.
  "inebachhkahcdepkbdkhchnpahladpnk", // Chrome Web Store item (owner's developer account).
] as const;
export const EXTENSION_ORIGINS = ALLOWED_EXTENSION_IDS.map(id => `chrome-extension://${id}`);
/** On "Quit anyway" a running stage is handed back quickly and repeats on the next start. */
const WORKER_SHUTDOWN_GRACE_SECONDS = "10";

export const SECRET_NAMES = [
  "local_token",
  "engine_token",
  "management_token",
  "recording_capability_key",
  "database_password",
] as const;
export type SecretName = (typeof SECRET_NAMES)[number];

/** Where code and binaries live: the runtime (Python, PostgreSQL, tools) and the Sauri sources. */
export interface Layout {
  runtimeDir: string;
  sourceRoot: string;
  portalDir: string;
}

/** What an installed Sauri.app carries next to its code (`Contents/Resources`, see scripts/stage.mjs). */
export function resourcesLayout(resources: string): Layout {
  return {
    runtimeDir: path.join(resources, "runtime"),
    sourceRoot: path.join(resources, "app-sources"),
    portalDir: path.join(resources, "portal"),
  };
}

/** The layout of a Sauri.app bundle, such as a staged update whose core runs the migration (design D12). */
export function bundleLayout(appPath: string): Layout {
  return resourcesLayout(path.join(appPath, "Contents", "Resources"));
}

export interface ServiceContext {
  layout: Layout;
  paths: AppPaths;
  folders: UserFolders;
  ports: PortPlan;
  localUserId?: string;
}

export class CoreError extends Error {
  constructor(
    readonly code: string,
    readonly detail = "",
  ) {
    super(detail ? `${code}: ${detail}` : code);
  }
}

export function secretFile(paths: AppPaths, name: SecretName): string {
  return path.join(paths.secretsDir, name);
}

/** Creates the internal credentials once (folder 0700, files 0600); values never reach a log. */
export function ensureSecrets(paths: AppPaths): void {
  ensurePrivateDir(paths.secretsDir);
  for (const name of SECRET_NAMES) {
    const file = secretFile(paths, name);
    const info = fs.lstatSync(file, { throwIfNoEntry: false });
    if (info && !info.isFile()) throw new CoreError("secret_not_a_file", name);
    if (info && info.size > 0) {
      fs.chmodSync(file, 0o600);
      continue;
    }
    // 32 random bytes as hex: valid for the local token check and safe inside connection URLs.
    fs.writeFileSync(file, `${randomBytes(32).toString("hex")}\n`, { mode: 0o600, flag: info ? "w" : "wx" });
    fs.chmodSync(file, 0o600);
  }
}

export function readSecret(paths: AppPaths, name: SecretName): string {
  return fs.readFileSync(secretFile(paths, name), "utf8").trim();
}

const bin = (ctx: ServiceContext, ...parts: string[]) => path.join(ctx.layout.runtimeDir, ...parts);
const python = (ctx: ServiceContext) => bin(ctx, "python", "bin", "python3");
const backendDir = (ctx: ServiceContext) => path.join(ctx.layout.sourceRoot, "backend");
const enginesConfig = (ctx: ServiceContext, file: string) => path.join(ctx.layout.sourceRoot, "scripts", "engines", file);

/** A minimal environment: nothing from the developer's shell (a stray DATABASE_URL, say) reaches a service. */
export function baseEnv(ctx: ServiceContext): Record<string, string> {
  const env: Record<string, string> = {
    PATH: [bin(ctx, "bin"), bin(ctx, "pg", "bin"), "/usr/bin", "/bin", "/usr/sbin", "/sbin"].join(":"),
    HOME: process.env.HOME ?? ctx.paths.home,
    LANG: process.env.LANG || "en_US.UTF-8",
    TMPDIR: process.env.TMPDIR || "/tmp",
    PYTHONNOUSERSITE: "1",
    PYTHONSAFEPATH: "1",
    PYTHONUNBUFFERED: "1",
    PYTHONPYCACHEPREFIX: path.join(ctx.paths.cacheDir, "pycache"),
  };
  for (const key of ["USER", "LOGNAME"]) if (process.env[key]) env[key] = process.env[key] as string;
  return env;
}

export function databaseUrl(ctx: ServiceContext): string {
  return `postgresql+asyncpg://${DB_USER}@/${DB_NAME}?host=${encodeURIComponent(ctx.paths.runDir)}`;
}

/** Environment of the API (`api: true`) and the worker, which never holds the management token. */
export function coreEnv(ctx: ServiceContext, opts: { api: boolean }): Record<string, string> {
  const { ports } = ctx;
  const env: Record<string, string> = {
    ...baseEnv(ctx),
    PYTHONPATH: [backendDir(ctx), bin(ctx, "components", "core")].join(":"),
    APP_ENV: "production",
    SAURI_AUTH_MODE: "local",
    SAURI_LOCAL_TOKEN_FILE: secretFile(ctx.paths, "local_token"),
    SAURI_EXTENSION_ORIGINS: EXTENSION_ORIGINS.join(","),
    SAURI_API_PORT: String(ports.api),
    QUEUE_KIND: "postgres",
    OBJECT_STORE_KIND: "filesystem",
    SAURI_RECORDINGS_DIR: ctx.folders.recordings,
    SAURI_PORTAL_DIR: ctx.layout.portalDir,
    DATABASE_URL: databaseUrl(ctx),
    DATABASE_PASSWORD_FILE: secretFile(ctx.paths, "database_password"),
    SAURI_ENGINE_TOKEN_FILE: secretFile(ctx.paths, "engine_token"),
    SAURI_RECORDING_CAPABILITY_KEY_FILE: secretFile(ctx.paths, "recording_capability_key"),
    SAURI_DEFAULT_LANGUAGE: "es",
    ASR_PROVIDER: "local",
    ASR_LOCAL_URL: `http://127.0.0.1:${ports.asr}`,
    DIARIZATION_LOCAL_URL: `http://127.0.0.1:${ports.diar}`,
    SUMMARIZATION_BASE_URL: `http://127.0.0.1:${ports.llm}/v1`,
    HOST_ENGINE_URL: `http://127.0.0.1:${ports.host}`,
    WORKER_SHUTDOWN_GRACE_SECONDS,
  };
  if (ctx.localUserId) env.SAURI_LOCAL_USER_ID = ctx.localUserId;
  if (opts.api) env.MANAGEMENT_TOKEN_FILE = secretFile(ctx.paths, "management_token");
  return env;
}

export const ENGINE_NAMES = ["host", "asr", "diar", "llm"] as const;
export type EngineName = (typeof ENGINE_NAMES)[number];
const ENGINE_SOURCES: Record<EngineName, { dir: string; component: string }> = {
  host: { dir: "host-engine", component: "host-engine" },
  asr: { dir: "asr-engine", component: "asr-engine" },
  diar: { dir: "diar-engine", component: "diar" },
  llm: { dir: "llm-engine", component: "llm-engine" },
};
export const ASR_MODEL_FILE = "ggml-large-v3-turbo-q5_0.bin";
export const VAD_MODEL_FILE = "ggml-silero-v6.2.0.bin";
export const LLM_MODEL_FILE = "Qwen3.5-9B-Q4_K_M.gguf";

export function asrProvenanceFile(paths: AppPaths): string {
  return path.join(paths.enginesDir, "asr-provenance", "provenance.json");
}

/** SAURI_PARAKEET_HOME: Parakeet's provenance and warm-up marker; its CLI stays in the runtime (SAURI_PARAKEET_CLI). */
export function parakeetHome(paths: AppPaths): string {
  return path.join(paths.enginesDir, "parakeet");
}

/**
 * Where the speaker runtime is: the downloaded component once installed, else the one a development runtime
 * carries (the installed app's runtime leaves it out, design D9). Null while it is in neither place.
 */
export function diarComponentDir(ctx: ServiceContext): string | null {
  for (const dir of [path.join(ctx.paths.componentsDir, "diar"), bin(ctx, "components", "diar")]) {
    if (fs.statSync(dir, { throwIfNoEntry: false })?.isDirectory()) return dir;
  }
  return null;
}

function componentDir(ctx: ServiceContext, name: EngineName): string {
  if (name === "diar") return diarComponentDir(ctx) ?? path.join(ctx.paths.componentsDir, "diar");
  return bin(ctx, "components", ENGINE_SOURCES[name].component);
}

/** The same variables `scripts/engines/native-engines.sh start` relies on, pointed at the runtime and user folders. */
export function engineEnv(ctx: ServiceContext, name: EngineName): Record<string, string> {
  const { paths, folders } = ctx;
  const env: Record<string, string> = {
    ...baseEnv(ctx),
    PYTHONPATH: [path.join(backendDir(ctx), "engine-common"), componentDir(ctx, name)].join(":"),
    SAURI_RECORDING_CAPABILITY_KEY_FILE: secretFile(paths, "recording_capability_key"),
    SAURI_MODELS_DIR: folders.models,
    SAURI_RECORDINGS_DIR: folders.recordings,
    SAURI_NATIVE_ENGINE_STATE_DIR: paths.runDir,
    SAURI_MODEL_CATALOG: enginesConfig(ctx, "model-catalog.json"),
    SAURI_ENGINE_HASHES_FILE: enginesConfig(ctx, "engine-hashes.json"),
    // Managed engines install inside Sauri's own folder, never the developer's ~/.local/share/sauri.
    SAURI_PARAKEET_HOME: parakeetHome(paths),
    // The runtime's own fluidaudiocli, next to its resource bundle; ensureParakeetProvenance vouches for it.
    SAURI_PARAKEET_CLI: bin(ctx, "bin", "fluidaudiocli"),
    SAURI_DIAR_VENV: path.join(paths.enginesDir, "diar-venv"),
    SAURI_HF_TOKEN_FILE: path.join(paths.secretsDir, "hf_token"),
  };
  if (name === "host") {
    env.SAURI_MANAGEMENT_TOKEN_FILE = secretFile(paths, "management_token");
    env.SAURI_ADOPT_ON_START = "0";
    // Downloadable components (design D9): where they install, the development copy, and where they come from.
    env.SAURI_COMPONENTS_DIR = paths.componentsDir;
    env.SAURI_BUNDLED_COMPONENTS_DIR = bin(ctx, "components");
    env.SAURI_RELEASES_REPO = releasesRepo();
    Object.assign(env, loopbackDownloadEnv());
  } else {
    env.SAURI_ENGINE_TOKEN_FILE = secretFile(paths, "engine_token");
  }
  if (name === "asr") {
    env.WHISPER_CLI = bin(ctx, "bin", "whisper-cli");
    env.SAURI_ASR_VAD_CLI = bin(ctx, "bin", "whisper-vad-speech-segments");
    env.ASR_MODEL_PATH = path.join(folders.models, ASR_MODEL_FILE);
    env.SAURI_ASR_VAD_MODEL_PATH = path.join(folders.models, VAD_MODEL_FILE);
    // asr_assets.provenance_path() is <SAURI_ASR_VENV>/../asr-provenance/provenance.json.
    env.SAURI_ASR_VENV = path.join(paths.enginesDir, "asr-venv");
  }
  if (name === "llm") {
    env.SAURI_LLAMA_SERVER = bin(ctx, "bin", "llama-server");
    env.SAURI_LLM_MODEL_FILE = path.join(folders.models, LLM_MODEL_FILE);
  }
  return env;
}

export function postgresSpec(ctx: ServiceContext): ServiceSpec {
  const pgdata = pgDataDir(ctx.folders);
  socketPath(ctx.paths.runDir, PG_SOCKET_PORT);
  const env = baseEnv(ctx);
  return {
    name: "postgres",
    command: bin(ctx, "pg", "bin", "postgres"),
    args: [
      "-D",
      pgdata,
      "-k",
      ctx.paths.runDir,
      "-p",
      String(PG_SOCKET_PORT),
      "-c",
      "listen_addresses=",
      "-c",
      "unix_socket_permissions=0700",
    ],
    env,
    logFile: path.join(ctx.paths.logsDir, "postgres.log"),
    pidFile: path.join(ctx.paths.runDir, "postgres.pid"),
    processMarker: pgdata,
    health: () =>
      commandHealth(
        bin(ctx, "pg", "bin", "pg_isready"),
        ["-q", "-h", ctx.paths.runDir, "-p", String(PG_SOCKET_PORT), "-U", DB_USER, "-d", "postgres"],
        env,
      ),
    // SIGINT is PostgreSQL's fast shutdown; only the postmaster is signalled.
    stopSignal: "SIGINT",
    stopTimeoutMs: 30_000,
    killGroup: false,
  };
}

export function apiSpec(ctx: ServiceContext): ServiceSpec {
  const port = String(ctx.ports.api);
  return {
    name: "api",
    command: python(ctx),
    // No access log: media URLs carry signed tokens in their path.
    args: ["-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", port, "--no-access-log"],
    cwd: backendDir(ctx),
    env: coreEnv(ctx, { api: true }),
    logFile: path.join(ctx.paths.logsDir, "api.log"),
    pidFile: path.join(ctx.paths.runDir, "api.pid"),
    processMarker: `app.main:app --host 127.0.0.1 --port ${port}`,
    health: () => httpHealth(`http://127.0.0.1:${port}/health`),
    stopTimeoutMs: 15_000,
  };
}

/** The worker has no HTTP endpoint: it is ready once it stays up. */
export function workerSpec(ctx: ServiceContext): ServiceSpec {
  return {
    name: "worker",
    command: python(ctx),
    args: ["-m", "app.worker"],
    cwd: backendDir(ctx),
    env: coreEnv(ctx, { api: false }),
    logFile: path.join(ctx.paths.logsDir, "worker.log"),
    pidFile: path.join(ctx.paths.runDir, "worker.pid"),
    processMarker: "-m app.worker",
    // Long enough for a failing import or a refused database connection to show up as a crash.
    readyAfterMs: 5000,
    stopTimeoutMs: 30_000,
  };
}

export type BlockedReason = "models_missing" | "component_missing" | "binary_unverified";
export type EnginePlan = { name: EngineName; spec: ServiceSpec } | { name: EngineName; blocked: BlockedReason };

export function engineSpec(ctx: ServiceContext, name: EngineName): ServiceSpec {
  const port = String(ctx.ports[name]);
  const args = [
    "-m",
    "uvicorn",
    "native_main:app",
    "--app-dir",
    path.join(backendDir(ctx), ENGINE_SOURCES[name].dir),
    "--host",
    "127.0.0.1",
    "--port",
    port,
  ];
  // Request lines of secret writes stay out of the host service's log.
  if (name === "host") args.push("--no-access-log");
  return {
    name: `${name}-engine`,
    command: python(ctx),
    args,
    env: engineEnv(ctx, name),
    logFile: path.join(ctx.paths.logsDir, `${name}-engine.log`),
    pidFile: path.join(ctx.paths.runDir, `${name}-engine.pid`),
    processMarker: `native_main:app --app-dir ${path.join(backendDir(ctx), ENGINE_SOURCES[name].dir)}`,
    // The host service answers /health only with its management token.
    health: () =>
      httpHealth(
        `http://127.0.0.1:${port}/health`,
        name === "host" ? { Authorization: `Bearer ${readSecret(ctx.paths, "management_token")}` } : {},
      ),
    stopTimeoutMs: 15_000,
  };
}

interface BinaryPin {
  size: number;
  sha256: string;
}

function sha256(file: string): string {
  return createHash("sha256").update(fs.readFileSync(file)).digest("hex");
}

function matchesPin(file: string, pin: BinaryPin | undefined): boolean {
  if (!pin) return false;
  const info = fs.statSync(file, { throwIfNoEntry: false });
  return !!info?.isFile() && info.size === pin.size && sha256(file) === pin.sha256;
}

/**
 * Records the runtime's whisper.cpp build as the ASR engine's verified installation, but only when both binaries
 * equal the builds pinned in engine-hashes.json. The engine still checks the record against the files at startup.
 */
export function ensureAsrProvenance(ctx: ServiceContext): boolean {
  const hashes = JSON.parse(fs.readFileSync(enginesConfig(ctx, "engine-hashes.json"), "utf8")) as {
    asr: { model_sha256: string; runtime_binary?: BinaryPin; vad: { model_sha256: string; runtime_binary?: BinaryPin } };
  };
  const cli = bin(ctx, "bin", "whisper-cli");
  const vad = bin(ctx, "bin", "whisper-vad-speech-segments");
  if (!matchesPin(cli, hashes.asr.runtime_binary) || !matchesPin(vad, hashes.asr.vad.runtime_binary)) return false;
  const record = {
    engine: "whisper.cpp",
    binary_sha256: hashes.asr.runtime_binary?.sha256,
    model_sha256: hashes.asr.model_sha256,
    vad_binary_sha256: hashes.asr.vad.runtime_binary?.sha256,
    vad_model_sha256: hashes.asr.vad.model_sha256,
  };
  const file = asrProvenanceFile(ctx.paths);
  ensurePrivateDir(path.dirname(file));
  fs.writeFileSync(`${file}.tmp`, `${JSON.stringify(record, null, 2)}\n`, { mode: 0o600 });
  fs.renameSync(`${file}.tmp`, file);
  return true;
}

/**
 * Records the runtime's fluidaudiocli as Parakeet's verified installation (`<parakeet home>/provenance.json`, the
 * record install-parakeet-engine.sh writes), but only when the binary equals its pin in the runtime manifest and that
 * build is of the commit engine-hashes.json pins. Otherwise any old record is removed and Whisper stays the engine.
 */
export function ensureParakeetProvenance(ctx: ServiceContext): boolean {
  const file = path.join(parakeetHome(ctx.paths), "provenance.json");
  try {
    const manifest = JSON.parse(fs.readFileSync(bin(ctx, "runtime-manifest.json"), "utf8")) as {
      artifacts: { name: string; commit?: string; binaries?: Record<string, { sha256: string }> }[];
    };
    const hashes = JSON.parse(fs.readFileSync(enginesConfig(ctx, "engine-hashes.json"), "utf8")) as {
      parakeet?: { source_commit?: string };
    };
    const fluid = manifest.artifacts.find((artifact) => artifact.name === "fluidaudio");
    const pin = fluid?.binaries?.fluidaudiocli?.sha256;
    const commit = hashes.parakeet?.source_commit;
    const cli = bin(ctx, "bin", "fluidaudiocli");
    const present = fs.statSync(cli, { throwIfNoEntry: false })?.isFile() === true;
    if (pin && commit && fluid?.commit === commit && present && sha256(cli) === pin) {
      const record = { source_commit: commit, binary_sha256: pin, origin: "bundled" };
      ensurePrivateDir(path.dirname(file));
      fs.writeFileSync(`${file}.tmp`, `${JSON.stringify(record, null, 2)}\n`, { mode: 0o600 });
      fs.renameSync(`${file}.tmp`, file);
      return true;
    }
  } catch {
    // An unreadable manifest vouches for nothing.
  }
  fs.rmSync(file, { force: true });
  return false;
}

/**
 * True when `local:default` of transcription means Parakeet on this Mac: the catalog's preferred model is installed
 * (its folder and an `installed` manifest from host-engine, which checked every file) and the runtime's
 * fluidaudiocli was vouched for (`ensureParakeetProvenance`, run when the engines start). The ASR engine makes the
 * same choice per request and checks the files again; this only decides whether the engine can start.
 */
export function parakeetActive(ctx: ServiceContext): boolean {
  try {
    const catalog = JSON.parse(fs.readFileSync(enginesConfig(ctx, "model-catalog.json"), "utf8")) as {
      models: { process: string; kind: string; preferred?: boolean; file?: string }[];
    };
    const preferred = catalog.models.find((m) => m.process === "transcription" && m.kind === "model" && m.preferred);
    if (!preferred?.file) return false;
    const folder = path.join(ctx.folders.models, preferred.file);
    const manifest = JSON.parse(fs.readFileSync(`${folder}.manifest.json`, "utf8")) as { status?: string };
    return (
      manifest.status === "installed" &&
      fs.statSync(folder, { throwIfNoEntry: false })?.isDirectory() === true &&
      fs.existsSync(path.join(parakeetHome(ctx.paths), "provenance.json"))
    );
  } catch {
    return false; // no catalog, no manifest or an unreadable one: Parakeet is not what local:default runs
  }
}

/**
 * The files the ASR engine's active model needs before the engine can start. One model runs per request: with
 * Parakeet active nothing of Whisper is needed (its model and voice detector serve Whisper only); with Whisper
 * active, both are. A model chosen by hand in Settings is checked by the engine itself, which refuses its requests
 * with a clear code when its files are missing (Settings offers only installed models).
 */
export function activeAsrFiles(ctx: ServiceContext): string[] {
  if (parakeetActive(ctx)) return [];
  return [ASR_MODEL_FILE, VAD_MODEL_FILE].map((file) => path.join(ctx.folders.models, file));
}

/** Which engines can start now, and why the others wait (models come in setup phase B). */
export function enginePlans(ctx: ServiceContext, names: readonly EngineName[] = ENGINE_NAMES): EnginePlan[] {
  return names.map((name): EnginePlan => {
    if (name === "diar" && diarComponentDir(ctx) === null) return { name, blocked: "component_missing" };
    if (name === "asr") {
      if (!activeAsrFiles(ctx).every((file) => fs.existsSync(file))) return { name, blocked: "models_missing" };
      // The runtime's whisper.cpp binaries are always there; the engine checks them at startup for every model.
      if (!ensureAsrProvenance(ctx)) return { name, blocked: "binary_unverified" };
    }
    return { name, spec: engineSpec(ctx, name) };
  });
}

/** Runs one command to completion; its output goes to `log`, stdout is also returned. */
export function runOnce(
  command: string,
  args: string[],
  opts: { env: Record<string, string>; cwd?: string; log: RotatingLog; timeoutMs?: number },
): Promise<{ code: number | null; stdout: string }> {
  return new Promise((resolve) => {
    opts.log.line(`running ${path.basename(command)} ${args[0] ?? ""}`);
    const child = spawn(command, args, { env: opts.env, cwd: opts.cwd, stdio: ["ignore", "pipe", "pipe"] });
    const out: Buffer[] = [];
    child.stdout.on("data", (chunk: Buffer) => {
      out.push(chunk);
      opts.log.write(chunk);
    });
    child.stderr.on("data", (chunk: Buffer) => opts.log.write(chunk));
    const timer = setTimeout(() => child.kill("SIGKILL"), opts.timeoutMs ?? 120_000);
    child.once("error", (error) => {
      opts.log.line(`${path.basename(command)} could not start: ${error.message}`);
      clearTimeout(timer);
      resolve({ code: null, stdout: "" });
    });
    child.once("close", (code) => {
      clearTimeout(timer);
      resolve({ code, stdout: Buffer.concat(out).toString("utf8") });
    });
  });
}

/** `initdb` into a temporary folder renamed at the end: an interrupted run never leaves a half cluster. */
export async function initDatabase(ctx: ServiceContext, log: RotatingLog): Promise<void> {
  const pgdata = pgDataDir(ctx.folders);
  if (fs.existsSync(path.join(pgdata, "PG_VERSION"))) return;
  if (fs.existsSync(pgdata) && fs.readdirSync(pgdata).length > 0) throw new CoreError("pgdata_not_empty", pgdata);
  const staging = `${pgdata}.init`;
  fs.rmSync(staging, { recursive: true, force: true });
  const result = await runOnce(
    bin(ctx, "pg", "bin", "initdb"),
    [
      "-D",
      staging,
      "-U",
      DB_USER,
      "--auth=scram-sha-256",
      `--pwfile=${secretFile(ctx.paths, "database_password")}`,
      "-E",
      "UTF8",
      "--no-locale",
    ],
    { env: baseEnv(ctx), log },
  );
  if (result.code !== 0) throw new CoreError("initdb_failed");
  fs.rmSync(pgdata, { recursive: true, force: true });
  fs.renameSync(staging, pgdata);
}

function pgClientEnv(ctx: ServiceContext): Record<string, string> {
  return { ...baseEnv(ctx), PGPASSWORD: readSecret(ctx.paths, "database_password") };
}

/** Creates the `sauri` database on first use, then applies the Alembic chain. */
export async function prepareDatabase(ctx: ServiceContext, log: RotatingLog): Promise<void> {
  const socket = ["-h", ctx.paths.runDir, "-p", String(PG_SOCKET_PORT), "-U", DB_USER];
  const exists = await runOnce(
    bin(ctx, "pg", "bin", "psql"),
    [...socket, "-d", "postgres", "-tAc", `SELECT 1 FROM pg_database WHERE datname = '${DB_NAME}'`],
    { env: pgClientEnv(ctx), log },
  );
  if (exists.code !== 0) throw new CoreError("database_unreachable");
  if (exists.stdout.trim() !== "1") {
    const created = await runOnce(bin(ctx, "pg", "bin", "createdb"), [...socket, DB_NAME], { env: pgClientEnv(ctx), log });
    if (created.code !== 0) throw new CoreError("createdb_failed");
  }
  const migrated = await runOnce(python(ctx), ["-m", "alembic", "upgrade", "head"], {
    env: coreEnv(ctx, { api: false }),
    cwd: backendDir(ctx),
    log,
    timeoutMs: 600_000,
  });
  if (migrated.code !== 0) throw new CoreError("migration_failed");
}

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;

/** `python -m app.local.bootstrap --name <name>`: creates (or finds) the local user and returns its id. */
export async function bootstrapLocalUser(ctx: ServiceContext, name: string, log: RotatingLog): Promise<string> {
  const result = await runOnce(python(ctx), ["-m", "app.local.bootstrap", "--name", name], {
    env: coreEnv(ctx, { api: false }),
    cwd: backendDir(ctx),
    log,
  });
  const id = result.stdout.trim().split("\n").pop() ?? "";
  if (result.code !== 0 || !UUID.test(id)) throw new CoreError("bootstrap_failed");
  return id;
}

export type ServiceSummary = { name: string; state: string; failed: boolean } | { name: string; blocked: BlockedReason };

/** Starts and stops every service in order; the tray and the quit flow read its summary. */
export class Core extends EventEmitter {
  private readonly supervisors = new Map<string, Supervisor>();
  private readonly blocked = new Map<string, BlockedReason>();

  constructor(
    private ctx: ServiceContext,
    private readonly log: RotatingLog,
  ) {
    super();
  }

  setContext(ctx: ServiceContext): void {
    this.ctx = ctx;
  }

  private async run(spec: ServiceSpec, readyMs: number): Promise<boolean> {
    const supervisor = new Supervisor(spec);
    this.supervisors.set(spec.name, supervisor);
    supervisor.on("state", () => this.emit("change"));
    supervisor.on("failed", () => this.emit("change"));
    await supervisor.start();
    const ready = await supervisor.waitReady(readyMs);
    this.log.line(`${spec.name} ${ready ? "ready" : `not ready after ${readyMs} ms`}`);
    return ready;
  }

  /** PostgreSQL first: setup needs it before the API exists. */
  async startDatabase(): Promise<void> {
    if (this.supervisors.has("postgres")) return;
    ensurePrivateDir(this.ctx.paths.runDir);
    if (!(await this.run(postgresSpec(this.ctx), 60_000))) throw new CoreError("postgres_not_ready");
  }

  get databaseRunning(): boolean {
    return this.supervisors.has("postgres");
  }

  /** `migrated`: the caller already ran the migrations (startup, with its copy first). */
  async startCore(opts: { migrated?: boolean } = {}): Promise<void> {
    await this.startDatabase();
    if (!opts.migrated) await prepareDatabase(this.ctx, this.log);
    if (!(await this.run(apiSpec(this.ctx), 90_000))) throw new CoreError("api_not_ready");
    if (!(await this.run(workerSpec(this.ctx), 15_000))) throw new CoreError("worker_not_ready");
  }

  /** Engines start together; one that cannot start is reported, never faked, and never blocks the portal. */
  async startEngines(): Promise<void> {
    const parakeet = ensureParakeetProvenance(this.ctx);
    this.log.line(`parakeet cli ${parakeet ? "verified" : "unverified: local:default runs whisper.cpp"}`);
    const plans = enginePlans(this.ctx);
    await Promise.all(
      plans.map(async (plan) => {
        if ("blocked" in plan) {
          this.blocked.set(`${plan.name}-engine`, plan.blocked);
          this.log.line(`${plan.name}-engine not started: ${plan.blocked}`);
          return;
        }
        await this.run(plan.spec, 120_000);
      }),
    );
    this.emit("change");
  }

  private retrying = false;
  /** Bumped by `stop()`, so a retry that was already running never starts an engine after it. */
  private generation = 0;

  /**
   * Starts the engines that were waiting for something setup phase B installs (a model, the speaker runtime) once
   * it is there; the main process calls this every few seconds. Unverified binaries keep waiting.
   */
  async startWaitingEngines(): Promise<string[]> {
    if (this.retrying || this.blocked.size === 0) return [];
    this.retrying = true;
    const started: string[] = [];
    const generation = this.generation;
    try {
      const waiting = ENGINE_NAMES.filter((name) => {
        const reason = this.blocked.get(`${name}-engine`);
        return reason !== undefined && reason !== "binary_unverified";
      });
      for (const plan of enginePlans(this.ctx, waiting)) {
        if ("blocked" in plan) {
          const name = `${plan.name}-engine`;
          if (this.blocked.get(name) !== plan.blocked) this.log.line(`${name} not started: ${plan.blocked}`);
          this.blocked.set(name, plan.blocked);
          continue;
        }
        if (generation !== this.generation) break;
        this.blocked.delete(plan.spec.name);
        this.log.line(`${plan.spec.name} can start now`);
        await this.run(plan.spec, 120_000);
        started.push(plan.spec.name);
      }
    } finally {
      this.retrying = false;
    }
    if (started.length > 0) this.emit("change");
    return started;
  }

  summary(): ServiceSummary[] {
    const running = [...this.supervisors.entries()].map(([name, supervisor]) => ({
      name,
      state: supervisor.state,
      failed: supervisor.failed,
    }));
    const waiting = [...this.blocked.entries()].map(([name, blocked]) => ({ name, blocked }));
    return [...running, ...waiting];
  }

  /** Reverse order: engines, worker, API, and PostgreSQL last. */
  async stop(): Promise<void> {
    this.generation += 1;
    const order = [...this.supervisors.keys()];
    const engines = order.filter((name) => name.endsWith("-engine"));
    await Promise.all(engines.map((name) => this.supervisors.get(name)?.stop()));
    for (const name of ["worker", "api", "postgres"]) await this.supervisors.get(name)?.stop();
    // A later start (after a folder move) begins from scratch.
    this.supervisors.clear();
    this.blocked.clear();
    this.emit("change");
    this.log.line("all services stopped");
  }
}
