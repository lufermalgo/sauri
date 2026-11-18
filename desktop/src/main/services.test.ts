import { createHash } from "node:crypto";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { catalogs } from "../i18n.ts";
import { appPaths, defaultFolders } from "./paths.ts";
import { portPlan } from "./ports.ts";
import {
  ASR_MODEL_FILE,
  asrProvenanceFile,
  coreEnv,
  databaseUrl,
  enginePlans,
  ensureAsrProvenance,
  ensureSecrets,
  SECRET_NAMES,
  secretFile,
  type ServiceContext,
  VAD_MODEL_FILE,
} from "./services.ts";

let dir: string;
let ctx: ServiceContext;

function writeBinary(file: string, content: string): { size: number; sha256: string } {
  fs.mkdirSync(path.dirname(file), { recursive: true });
  fs.writeFileSync(file, content, { mode: 0o755 });
  return { size: Buffer.byteLength(content), sha256: createHash("sha256").update(content).digest("hex") };
}

beforeEach(() => {
  dir = fs.mkdtempSync(path.join(os.tmpdir(), "sauri-services-"));
  const paths = appPaths({ dev: true, home: dir });
  const runtimeDir = path.join(dir, "runtime");
  const sourceRoot = path.join(dir, "src");
  const cli = writeBinary(path.join(runtimeDir, "bin", "whisper-cli"), "synthetic whisper-cli");
  const vad = writeBinary(path.join(runtimeDir, "bin", "whisper-vad-speech-segments"), "synthetic vad");
  fs.mkdirSync(path.join(sourceRoot, "scripts", "engines"), { recursive: true });
  fs.writeFileSync(
    path.join(sourceRoot, "scripts", "engines", "engine-hashes.json"),
    JSON.stringify({
      asr: { model_sha256: "a".repeat(64), runtime_binary: cli, vad: { model_sha256: "b".repeat(64), runtime_binary: vad } },
    }),
  );
  ctx = {
    layout: { runtimeDir, sourceRoot, portalDir: path.join(dir, "portal") },
    paths,
    folders: defaultFolders(paths),
    ports: portPlan(18100),
    localUserId: "6f1c2a52-3b2e-4a55-9d5b-1d2f3e4a5b6c",
  };
});

afterEach(() => fs.rmSync(dir, { recursive: true, force: true }));

describe("internal credentials", () => {
  it("creates each secret once, private, as 32 random bytes in hex", () => {
    ensureSecrets(ctx.paths);
    expect(fs.statSync(ctx.paths.secretsDir).mode & 0o777).toBe(0o700);
    const first = SECRET_NAMES.map((name) => fs.readFileSync(secretFile(ctx.paths, name), "utf8"));
    for (const [index, name] of SECRET_NAMES.entries()) {
      expect(first[index]).toMatch(/^[0-9a-f]{64}\n$/);
      expect(fs.statSync(secretFile(ctx.paths, name)).mode & 0o777).toBe(0o600);
    }
    expect(new Set(first).size).toBe(SECRET_NAMES.length);
    ensureSecrets(ctx.paths);
    expect(SECRET_NAMES.map((name) => fs.readFileSync(secretFile(ctx.paths, name), "utf8"))).toEqual(first);
  });
});

describe("service environment", () => {
  it("runs the API in local mode on the planned port with the socket database", () => {
    process.env.DATABASE_URL = "postgresql://developer-shell/should-not-leak";
    try {
      const env = coreEnv(ctx, { api: true });
      expect(env).toMatchObject({
        SAURI_AUTH_MODE: "local",
        SAURI_API_PORT: "18100",
        QUEUE_KIND: "postgres",
        OBJECT_STORE_KIND: "filesystem",
        SAURI_LOCAL_USER_ID: ctx.localUserId,
        SAURI_RECORDINGS_DIR: ctx.folders.recordings,
        ASR_LOCAL_URL: "http://127.0.0.1:18101",
        HOST_ENGINE_URL: "http://127.0.0.1:18105",
        PYTHONNOUSERSITE: "1",
        PYTHONSAFEPATH: "1",
      });
      expect(env.DATABASE_URL).toBe(databaseUrl(ctx));
      expect(env.DATABASE_URL).toContain(`?host=${encodeURIComponent(ctx.paths.runDir)}`);
      expect(env.SAURI_EXTENSION_ORIGINS).toContain("chrome-extension://ilnkkojmkfnbdilogldabpodoobfigce");
      expect(env.MANAGEMENT_TOKEN_FILE).toBe(secretFile(ctx.paths, "management_token"));
      expect(coreEnv(ctx, { api: false }).MANAGEMENT_TOKEN_FILE).toBeUndefined();
      expect(Object.values(env).join("\n")).not.toContain("should-not-leak");
    } finally {
      delete process.env.DATABASE_URL;
    }
  });
});

describe("engines", () => {
  it("waits for models and the speaker runtime instead of faking engines", () => {
    const plans = enginePlans(ctx);
    expect(plans.map((plan) => ("blocked" in plan ? `${plan.name}:${plan.blocked}` : plan.name))).toEqual([
      "host",
      "asr:models_missing",
      "diar:component_missing",
      "llm",
    ]);
  });

  it("records the pinned runtime whisper.cpp build as the ASR provenance", () => {
    fs.mkdirSync(ctx.folders.models, { recursive: true });
    for (const file of [ASR_MODEL_FILE, VAD_MODEL_FILE]) fs.writeFileSync(path.join(ctx.folders.models, file), "model");
    fs.mkdirSync(path.join(ctx.layout.runtimeDir, "components", "diar"), { recursive: true });
    const plans = enginePlans(ctx);
    expect(plans.every((plan) => "spec" in plan)).toBe(true);
    const record = JSON.parse(fs.readFileSync(asrProvenanceFile(ctx.paths), "utf8"));
    expect(record).toEqual({
      engine: "whisper.cpp",
      binary_sha256: createHash("sha256").update("synthetic whisper-cli").digest("hex"),
      model_sha256: "a".repeat(64),
      vad_binary_sha256: createHash("sha256").update("synthetic vad").digest("hex"),
      vad_model_sha256: "b".repeat(64),
    });
    const asr = plans.find((plan) => plan.name === "asr");
    expect(asr && "spec" in asr ? asr.spec.env.SAURI_ASR_VENV : "").toBe(path.join(ctx.paths.enginesDir, "asr-venv"));
  });

  it("does not vouch for a runtime binary that differs from its pin", () => {
    fs.writeFileSync(path.join(ctx.layout.runtimeDir, "bin", "whisper-cli"), "tampered whisper-cli");
    expect(ensureAsrProvenance(ctx)).toBe(false);
    expect(fs.existsSync(asrProvenanceFile(ctx.paths))).toBe(false);
  });
});

describe("texts", () => {
  it("has the same keys in Spanish and English", () => {
    expect(Object.keys(catalogs.en).sort()).toEqual(Object.keys(catalogs.es).sort());
  });
});

describe("runtime pins", () => {
  it("match the runtime manifest", () => {
    const repo = path.resolve(import.meta.dirname, "..", "..", "..");
    const hashes = JSON.parse(fs.readFileSync(path.join(repo, "scripts/engines/engine-hashes.json"), "utf8"));
    const manifest = JSON.parse(fs.readFileSync(path.join(repo, "desktop/runtime-manifest.json"), "utf8"));
    const whisper = manifest.artifacts.find((artifact: { name: string }) => artifact.name === "whisper.cpp");
    expect(hashes.asr.runtime_binary.sha256).toBe(whisper.binaries["whisper-cli"].sha256);
    expect(hashes.asr.vad.runtime_binary.sha256).toBe(whisper.binaries["whisper-vad-speech-segments"].sha256);
  });
});
