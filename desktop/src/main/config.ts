// config.json: user folders, the local user, the setup step and preferences (design D11, "Modelos de Datos").
import { randomUUID } from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import { type AppPaths, defaultFolders, FOLDER_KINDS, type UserFolders } from "./paths.ts";

export const SCHEMA_VERSION = 1;
/** Phase A (this app) owns identity and folders; phase B (portal /bienvenida) owns models and extension. */
export const SETUP_STEPS = ["identity", "folders", "models", "extension", "done"] as const;
export type SetupStep = (typeof SETUP_STEPS)[number];
export type Locale = "es" | "en";

export interface AppConfig {
  schemaVersion: typeof SCHEMA_VERSION;
  installId: string;
  setupStep: SetupStep;
  locale: Locale;
  /** Kept so an interrupted setup can still create the local user with the chosen name. */
  localUserName?: string;
  localUserId?: string;
  paths?: UserFolders;
  launchAtLogin: boolean;
  autoUpdate: boolean;
  appVersionOfData?: string;
}

export class ConfigError extends Error {
  constructor(readonly code: "config_unreadable" | "config_invalid" | "config_newer") {
    super(code);
  }
}

export function defaultConfig(): AppConfig {
  return {
    schemaVersion: SCHEMA_VERSION,
    installId: randomUUID(),
    setupStep: "identity",
    locale: "es",
    launchAtLogin: false,
    autoUpdate: true,
  };
}

/** The folders setup shows: the saved ones as they are (never renamed or moved), else the English defaults. */
export function setupFolders(config: AppConfig, paths: Pick<AppPaths, "home" | "dev">): UserFolders {
  return config.paths ?? defaultFolders(paths);
}

/** Phase A is finished once the local user exists; the core can start from then on. */
export function phaseADone(config: AppConfig): boolean {
  return config.setupStep !== "identity" && config.setupStep !== "folders";
}

function isString(value: unknown): value is string {
  return typeof value === "string" && value.length > 0;
}

function parse(raw: unknown): AppConfig {
  if (typeof raw !== "object" || raw === null) throw new ConfigError("config_invalid");
  const value = raw as Record<string, unknown>;
  if (typeof value.schemaVersion !== "number") throw new ConfigError("config_invalid");
  // A newer app wrote this file: an older one must not rewrite it with fields it does not know.
  if (value.schemaVersion > SCHEMA_VERSION) throw new ConfigError("config_newer");
  if (value.schemaVersion !== SCHEMA_VERSION) throw new ConfigError("config_invalid");
  if (!isString(value.installId) || !SETUP_STEPS.includes(value.setupStep as SetupStep)) {
    throw new ConfigError("config_invalid");
  }
  let paths: UserFolders | undefined;
  if (value.paths !== undefined) {
    const raw = value.paths as Record<string, unknown>;
    if (typeof raw !== "object" || raw === null || !FOLDER_KINDS.every((kind) => isString(raw[kind]))) {
      throw new ConfigError("config_invalid");
    }
    paths = { recordings: raw.recordings as string, database: raw.database as string, models: raw.models as string };
  }
  const config: AppConfig = {
    schemaVersion: SCHEMA_VERSION,
    installId: value.installId,
    setupStep: value.setupStep as SetupStep,
    locale: value.locale === "en" ? "en" : "es",
    launchAtLogin: value.launchAtLogin === true,
    autoUpdate: value.autoUpdate !== false,
  };
  if (isString(value.localUserName)) config.localUserName = value.localUserName;
  if (isString(value.localUserId)) config.localUserId = value.localUserId;
  if (paths) config.paths = paths;
  if (isString(value.appVersionOfData)) config.appVersionOfData = value.appVersionOfData;
  if (phaseADone(config) && (!config.paths || !config.localUserId)) throw new ConfigError("config_invalid");
  return config;
}

/** The saved configuration, or a fresh one (not yet saved) when there is none. */
export function loadConfig(file: string): AppConfig {
  let text: string;
  try {
    text = fs.readFileSync(file, "utf8");
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === "ENOENT") return defaultConfig();
    throw new ConfigError("config_unreadable");
  }
  let raw: unknown;
  try {
    raw = JSON.parse(text);
  } catch {
    throw new ConfigError("config_invalid");
  }
  return parse(raw);
}

/** Atomic replace: a crash mid-write leaves the previous file intact. */
export function saveConfig(file: string, config: AppConfig): void {
  fs.mkdirSync(path.dirname(file), { recursive: true, mode: 0o700 });
  const temporary = `${file}.${process.pid}.tmp`;
  const fd = fs.openSync(temporary, "w", 0o600);
  try {
    fs.writeSync(fd, `${JSON.stringify(config, null, 2)}\n`);
    fs.fsyncSync(fd);
  } finally {
    fs.closeSync(fd);
  }
  fs.renameSync(temporary, file);
}
