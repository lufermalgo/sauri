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
  diarComponentDir,
  engineEnv,
  enginePlans,
  ensureAsrProvenance,
  ensureParakeetProvenance,
  ensureSecrets,
  SECRET_NAMES,
  secretFile,
  parakeetHome,
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
  const fluid = writeBinary(path.join(runtimeDir, "bin", "fluidaudiocli"), "synthetic fluidaudiocli");
  fs.writeFileSync(
    path.join(runtimeDir, "runtime-manifest.json"),
    JSON.stringify({
      artifacts: [{ name: "fluidaudio", commit: "c".repeat(40), binaries: { fluidaudiocli: { sha256: fluid.sha256 } } }],
    }),
  );
  fs.mkdirSync(path.join(sourceRoot, "scripts", "engines"), { recursive: true });
  fs.writeFileSync(
    path.join(sourceRoot, "scripts", "engines", "engine-hashes.json"),
    JSON.stringify({
      asr: { model_sha256: "a".repeat(64), runtime_binary: cli, vad: { model_sha256: "b".repeat(64), runtime_binary: vad } },
      parakeet: { source_commit: "c".repeat(40) },
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
      // Exactly the documented allow-list, nothing wider.
      expect(env.SAURI_EXTENSION_ORIGINS).toBe(
        "chrome-extension://ilnkkojmkfnbdilogldabpodoobfigce,chrome-extension://inebachhkahcdepkbdkhchnpahladpnk",
      );
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

  it("starts the speaker engine from the downloaded component, which wins over a development copy", () => {
    const bundled = path.join(ctx.layout.runtimeDir, "components", "diar");
    fs.mkdirSync(bundled, { recursive: true });
    expect(diarComponentDir(ctx)).toBe(bundled);
    const installed = path.join(ctx.paths.componentsDir, "diar");
    fs.mkdirSync(installed, { recursive: true });
    expect(diarComponentDir(ctx)).toBe(installed);
    const diar = enginePlans(ctx, ["diar"])[0];
    expect(diar && "spec" in diar ? diar.spec.env.PYTHONPATH.split(":") : []).toContain(installed);
  });

  it("tells the host service where components go and where they come from, loopback only on request", () => {
    const saved = { ...process.env };
    try {
      process.env.SAURI_RELEASES_REPO = "owner/sauri-app";
      process.env.SAURI_RELEASES_BASE_URL = "http://127.0.0.1:18999";
      delete process.env.SAURI_ALLOW_LOOPBACK_DOWNLOADS;
      const plain = engineEnv(ctx, "host");
      expect(plain).toMatchObject({
        SAURI_COMPONENTS_DIR: ctx.paths.componentsDir,
        SAURI_BUNDLED_COMPONENTS_DIR: path.join(ctx.layout.runtimeDir, "components"),
        SAURI_RELEASES_REPO: "owner/sauri-app",
      });
      expect(plain.SAURI_ALLOW_LOOPBACK_DOWNLOADS).toBeUndefined();
      expect(plain.SAURI_RELEASES_BASE_URL).toBeUndefined();
      process.env.SAURI_ALLOW_LOOPBACK_DOWNLOADS = "1";
      expect(engineEnv(ctx, "host")).toMatchObject({
        SAURI_ALLOW_LOOPBACK_DOWNLOADS: "1",
        SAURI_RELEASES_BASE_URL: "http://127.0.0.1:18999",
      });
      delete process.env.SAURI_RELEASES_REPO;
      expect(engineEnv(ctx, "host").SAURI_RELEASES_REPO).toBe("lufermalgo/sauri-app");
      process.env.SAURI_RELEASES_REPO = "";
      expect(engineEnv(ctx, "host").SAURI_RELEASES_REPO).toBe("");
      expect(engineEnv(ctx, "asr").SAURI_COMPONENTS_DIR).toBeUndefined();
    } finally {
      process.env = saved;
    }
  });

  it("does not vouch for a runtime binary that differs from its pin", () => {
    fs.writeFileSync(path.join(ctx.layout.runtimeDir, "bin", "whisper-cli"), "tampered whisper-cli");
    expect(ensureAsrProvenance(ctx)).toBe(false);
    expect(fs.existsSync(asrProvenanceFile(ctx.paths))).toBe(false);
  });
});

describe("parakeet", () => {
  const record = () => path.join(parakeetHome(ctx.paths), "provenance.json");

  it("vouches for the runtime's fluidaudiocli when it equals its pin and the pinned commit", () => {
    expect(ensureParakeetProvenance(ctx)).toBe(true);
    expect(JSON.parse(fs.readFileSync(record(), "utf8"))).toEqual({
      source_commit: "c".repeat(40),
      binary_sha256: createHash("sha256").update("synthetic fluidaudiocli").digest("hex"),
      origin: "bundled",
    });
    for (const name of ["host", "asr"] as const) {
      expect(engineEnv(ctx, name)).toMatchObject({
        SAURI_PARAKEET_HOME: parakeetHome(ctx.paths),
        SAURI_PARAKEET_CLI: path.join(ctx.layout.runtimeDir, "bin", "fluidaudiocli"),
      });
    }
  });

  it("removes the record when the binary or the commit no longer match", () => {
    expect(ensureParakeetProvenance(ctx)).toBe(true);
    fs.writeFileSync(path.join(ctx.layout.runtimeDir, "bin", "fluidaudiocli"), "re-signed fluidaudiocli");
    expect(ensureParakeetProvenance(ctx)).toBe(false);
    expect(fs.existsSync(record())).toBe(false);
    fs.writeFileSync(path.join(ctx.layout.runtimeDir, "bin", "fluidaudiocli"), "synthetic fluidaudiocli");
    const hashes = path.join(ctx.layout.sourceRoot, "scripts", "engines", "engine-hashes.json");
    fs.writeFileSync(hashes, JSON.stringify({ parakeet: { source_commit: "d".repeat(40) } }));
    expect(ensureParakeetProvenance(ctx)).toBe(false);
    fs.rmSync(path.join(ctx.layout.runtimeDir, "runtime-manifest.json"));
    expect(ensureParakeetProvenance(ctx)).toBe(false);
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
    const fluid = manifest.artifacts.find((artifact: { name: string }) => artifact.name === "fluidaudio");
    expect(fluid.commit).toBe(hashes.parakeet.source_commit);
  });
});
