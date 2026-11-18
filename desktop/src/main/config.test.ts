import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { type AppConfig, ConfigError, defaultConfig, loadConfig, phaseADone, SCHEMA_VERSION, saveConfig } from "./config.ts";

let dir: string;
let file: string;

beforeEach(() => {
  dir = fs.mkdtempSync(path.join(os.tmpdir(), "sauri-config-"));
  file = path.join(dir, "Sauri", "config.json");
});

afterEach(() => fs.rmSync(dir, { recursive: true, force: true }));

const complete = (): AppConfig => ({
  ...defaultConfig(),
  setupStep: "models",
  locale: "en",
  localUserName: "Ana Pérez",
  localUserId: "6f1c2a52-3b2e-4a55-9d5b-1d2f3e4a5b6c",
  paths: { recordings: "/Volumes/Disco/Grabaciones", database: "/Users/ana/Sauri/Base de datos", models: "/Users/ana/Sauri/Modelos" },
  launchAtLogin: true,
  autoUpdate: false,
  appVersionOfData: "1.0.0",
});

const sauriFiles = () => fs.readdirSync(path.dirname(file));

describe("config", () => {
  it("starts with a fresh, unsaved configuration at the first setup step", () => {
    const config = loadConfig(file);
    expect(config).toMatchObject({ schemaVersion: SCHEMA_VERSION, setupStep: "identity", locale: "es", launchAtLogin: false });
    expect(config.installId).toMatch(/^[0-9a-f-]{36}$/);
    expect(fs.existsSync(file)).toBe(false);
  });

  it("round-trips every field through an atomic, private file", () => {
    const config = complete();
    saveConfig(file, config);
    expect(loadConfig(file)).toEqual(config);
    expect(fs.statSync(file).mode & 0o777).toBe(0o600);
    expect(sauriFiles()).toEqual(["config.json"]);
  });

  it("refuses a file written by a newer schema instead of rewriting it", () => {
    saveConfig(file, complete());
    const raw = JSON.parse(fs.readFileSync(file, "utf8"));
    fs.writeFileSync(file, JSON.stringify({ ...raw, schemaVersion: SCHEMA_VERSION + 1 }));
    expect(() => loadConfig(file)).toThrowError(new ConfigError("config_newer"));
  });

  it.each([
    ["not JSON", "{"],
    ["no schema version", JSON.stringify({ installId: "x", setupStep: "identity" })],
    ["an old schema version", JSON.stringify({ schemaVersion: 0, installId: "x", setupStep: "identity" })],
    ["an unknown step", JSON.stringify({ schemaVersion: 1, installId: "x", setupStep: "later" })],
    ["incomplete folders", JSON.stringify({ schemaVersion: 1, installId: "x", setupStep: "folders", paths: { recordings: "/a" } })],
    ["phase A done without its user", JSON.stringify({ schemaVersion: 1, installId: "x", setupStep: "done", paths: complete().paths })],
  ])("rejects %s", (_label, text) => {
    fs.mkdirSync(path.dirname(file), { recursive: true });
    fs.writeFileSync(file, text);
    expect(() => loadConfig(file)).toThrowError(ConfigError);
  });

  it("knows when phase A is finished", () => {
    expect(phaseADone(defaultConfig())).toBe(false);
    expect(phaseADone({ ...defaultConfig(), setupStep: "folders" })).toBe(false);
    for (const step of ["models", "extension", "done"] as const) expect(phaseADone({ ...complete(), setupStep: step })).toBe(true);
  });
});
