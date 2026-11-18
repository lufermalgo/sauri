// Setup phase A (Requirement 6): hardware, name and folders, then initdb + bootstrap of the local user. Each answer
// is saved at once, so a setup interrupted at any point resumes at the pending step.
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { type BrowserWindow, dialog, type IpcMainInvokeEvent, ipcMain } from "electron";
import { type Locale, type MessageKey, t } from "../i18n.ts";
import { CHANNELS, type FinishResult, type SetupState, validateName, type View } from "../shared/setup-api.ts";
import type { AppConfig } from "./config.ts";
import { inspectFolders, prepareFolders } from "./folders.ts";
import { type CatalogModel, checkHardware, freeBytes, type HardwareReport, macosVersion } from "./hardware.ts";
import { type AppPaths, defaultFolders, FOLDER_KINDS, type FolderKind, type UserFolders } from "./paths.ts";
import {
  bootstrapLocalUser,
  type Core,
  CoreError,
  ensureSecrets,
  initDatabase,
  type Layout,
  prepareDatabase,
  type ServiceContext,
} from "./services.ts";
import type { RotatingLog } from "./supervisor.ts";

export interface SetupDeps {
  paths: AppPaths;
  layout: Layout;
  config: () => AppConfig;
  update: (change: Partial<AppConfig>) => AppConfig;
  context: (folders: UserFolders) => ServiceContext;
  core: (ctx: ServiceContext) => Core;
  log: RotatingLog;
  window: () => BrowserWindow | null;
  onLocale: (locale: Locale) => void;
  /** The app's own actions behind the startup and error views. */
  retry: () => void;
  openLogs: () => void;
  quit: () => void;
}

interface RuntimeManifest {
  minimum_macos: string;
  downloadable_size_mb: number;
}

function readJson<T>(file: string): T {
  return JSON.parse(fs.readFileSync(file, "utf8")) as T;
}

export function hardwareReport(layout: Layout, home: string): HardwareReport {
  const manifest = readJson<RuntimeManifest>(path.join(layout.runtimeDir, "runtime-manifest.json"));
  const catalog = readJson<{ models: CatalogModel[] }>(
    path.join(layout.sourceRoot, "scripts", "engines", "model-catalog.json"),
  );
  return checkHardware({
    arch: process.arch,
    macosVersion: macosVersion(),
    memoryBytes: os.totalmem(),
    diskFreeBytes: freeBytes(home),
    minimumMacos: manifest.minimum_macos,
    models: catalog.models,
    componentsBytes: Math.round(manifest.downloadable_size_mb * 1e6),
  });
}

function fromSetupWindow(event: IpcMainInvokeEvent): boolean {
  return event.senderFrame?.url.startsWith("file:") === true;
}

/** Registers the setup handlers; `done` resolves once the local user exists and phase A is saved as finished. */
export class SetupController {
  private finishing: Promise<FinishResult> | undefined;
  private resolveDone: (() => void) | undefined;
  readonly done: Promise<void>;
  mode: SetupState["mode"] = "setup";
  private lastView: View | undefined;

  constructor(private readonly deps: SetupDeps) {
    this.done = new Promise((resolve) => {
      this.resolveDone = resolve;
    });
    this.register();
  }

  private handle(channel: string, listener: (...args: unknown[]) => unknown): void {
    ipcMain.removeHandler(channel);
    ipcMain.handle(channel, (event, ...args) => {
      if (!fromSetupWindow(event)) throw new Error("forbidden");
      return listener(...args);
    });
  }

  private register(): void {
    const { deps } = this;
    this.handle(CHANNELS.state, (): SetupState => {
      const config = deps.config();
      return {
        mode: this.mode,
        step: config.setupStep === "folders" ? "folders" : "identity",
        locale: config.locale,
        name: config.localUserName ?? "",
        folders: config.paths ?? defaultFolders(deps.paths),
        view: this.lastView,
      };
    });
    this.handle(CHANNELS.hardware, () => hardwareReport(deps.layout, deps.paths.home));
    this.handle(CHANNELS.locale, (locale) => {
      const value: Locale = locale === "en" ? "en" : "es";
      deps.update({ locale: value });
      deps.onLocale(value);
    });
    this.handle(CHANNELS.identity, (raw) => {
      const result = validateName(raw);
      if (!result.ok) return result;
      deps.update({ localUserName: result.name, setupStep: "folders" });
      return { ok: true };
    });
    this.handle(CHANNELS.back, () => {
      deps.update({ setupStep: "identity" });
    });
    this.handle(CHANNELS.inspect, (folders) => inspectFolders(folders as UserFolders, deps.config().installId));
    this.handle(CHANNELS.choose, async (kind) => {
      const window = deps.window();
      const options: Electron.OpenDialogOptions = {
        title: t(deps.config().locale, `folder.${kind as FolderKind}` as MessageKey),
        properties: ["openDirectory", "createDirectory"],
      };
      const result = window ? await dialog.showOpenDialog(window, options) : await dialog.showOpenDialog(options);
      return result.canceled ? null : (result.filePaths[0] ?? null);
    });
    this.handle(CHANNELS.finish, (folders) => {
      this.finishing ??= this.finish(folders as UserFolders).finally(() => {
        this.finishing = undefined;
      });
      return this.finishing;
    });
    this.handle(CHANNELS.retry, () => deps.retry());
    this.handle(CHANNELS.logs, () => deps.openLogs());
    this.handle(CHANNELS.quit, () => deps.quit());
  }

  show(view: View): void {
    this.lastView = view;
    this.deps.window()?.webContents.send(CHANNELS.view, view);
  }

  private async finish(raw: UserFolders): Promise<FinishResult> {
    const { deps } = this;
    const config = deps.config();
    if (config.setupStep !== "folders" || !config.localUserName) return { ok: false };
    const folders = Object.fromEntries(FOLDER_KINDS.map((kind) => [kind, String(raw[kind] ?? "")])) as UserFolders;
    const problems = prepareFolders(folders, config.installId);
    if (problems.length > 0) return { ok: false, folders: problems };
    deps.update({ paths: folders });
    const ctx = deps.context(folders);
    try {
      this.show({ view: "progress", key: "init.secrets" });
      ensureSecrets(deps.paths);
      this.show({ view: "progress", key: "init.database" });
      await initDatabase(ctx, deps.log);
      const core = deps.core(ctx);
      await core.startDatabase();
      this.show({ view: "progress", key: "init.migrate" });
      await prepareDatabase(ctx, deps.log);
      this.show({ view: "progress", key: "init.user" });
      const localUserId = await bootstrapLocalUser(ctx, config.localUserName, deps.log);
      deps.update({ localUserId, setupStep: "models" });
      deps.log.line("setup phase A finished");
      this.mode = "startup";
      this.resolveDone?.();
      return { ok: true };
    } catch (error) {
      const code = error instanceof CoreError ? error.code : "unexpected";
      deps.log.line(`setup phase A failed: ${error instanceof Error ? error.message : String(error)}`);
      return { ok: false, message: t(deps.config().locale, "init.error", { code }) };
    }
  }
}
