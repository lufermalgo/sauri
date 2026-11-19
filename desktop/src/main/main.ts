// Sauri desktop: one instance, setup phase A when needed, then PostgreSQL and the API, the portal in its window and
// the menu-bar icon; the engines and then the worker start behind the open window. Closing the window keeps the
// services running; quitting asks first when meetings are being processed.
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { spawn } from "node:child_process";
import { app, BrowserWindow, dialog, type IpcMainInvokeEvent, ipcMain, Menu, shell } from "electron";
import { formatGigabytes, type Locale, type MessageKey, plural, t } from "../i18n.ts";
import { PORTAL_CHANNELS, type RelocateResult, type ServicesStatus } from "../shared/portal-api.ts";
import { setLaunchAtLogin } from "./autostart.ts";
import { type AppConfig, ConfigError, loadConfig, phaseADone, saveConfig } from "./config.ts";
import { appPaths, FOLDER_KINDS, type FolderKind, folderProblems, PathError, socketPath, type UserFolders } from "./paths.ts";
import { folderUsage, relocate } from "./relocate.ts";
import { busyPorts, DEFAULT_API_PORT, portPlan, portsToCheck } from "./ports.ts";
import {
  bundleLayout,
  Core,
  CoreError,
  ensureSecrets,
  type Layout,
  PG_SOCKET_PORT,
  prepareDatabase,
  readSecret,
  resourcesLayout,
  type ServiceContext,
} from "./services.ts";
import { releaseSource } from "./releases.ts";
import { UpdateController } from "./update-menu.ts";
import { type ApplyDeps, migrateOnStart, swapBundle } from "./updater.ts";
import { SetupController } from "./setup.ts";
import { fetchLocalStatus } from "./status.ts";
import { RotatingLog } from "./supervisor.ts";
import { SauriTray, trayStatus } from "./tray.ts";
import {
  afterExitSweep,
  appBundleOf,
  type FolderTarget,
  internalPaths,
  planUninstall,
  runUninstall,
  type UninstallPlan,
  type UninstallReport,
} from "./uninstall.ts";

const DIST = import.meta.dirname;
const dev = process.env.SAURI_DEV === "1" || !app.isPackaged;
// SAURI_DESKTOP_HOME and SAURI_API_PORT isolate a test run (a temporary home, another port block) in development
// and in the installed app alike; a normal launch from Finder sets neither.
const paths = appPaths({ dev, home: process.env.SAURI_DESKTOP_HOME });
const ports = portPlan(process.env.SAURI_API_PORT ? Number(process.env.SAURI_API_PORT) : DEFAULT_API_PORT);
/** electron-builder.json appId: macOS keeps preferences and saved window state under it. */
const APP_ID = "com.sauri.desktop";

function resolveLayout(): Layout {
  if (!dev) return resourcesLayout(process.resourcesPath);
  const repo = path.resolve(DIST, "..", "..");
  return {
    runtimeDir:
      process.env.SAURI_RUNTIME_DIR ?? path.join(os.homedir(), "Library", "Caches", "sauri-runtime-build", "runtime-current"),
    sourceRoot: repo,
    portalDir: process.env.SAURI_PORTAL_DIR ?? path.join(repo, "desktop", ".dev-portal"),
  };
}

app.setName(dev ? "Sauri-dev" : "Sauri");
app.setPath("userData", paths.electronDir);
app.setAppLogsPath(paths.logsDir);

const single = app.requestSingleInstanceLock();
if (!single) app.quit();

const layout = resolveLayout();
const log = new RotatingLog(path.join(paths.logsDir, "desktop.log"));
let config: AppConfig;
let core: Core | undefined;
let tray: SauriTray | undefined;
let setupWindow: BrowserWindow | null = null;
/** On a normal start (setup already done) the setup window stays hidden; it shows only for first run or an error. */
let quietStartup = false;
let portalWindow: BrowserWindow | null = null;
let controller: SetupController | undefined;
let started = false;
let quitting = false;
let poll: NodeJS.Timeout | undefined;
let updater: UpdateController | undefined;

const locale = (): Locale => config?.locale ?? "es";

function update(change: Partial<AppConfig>): AppConfig {
  config = { ...config, ...change };
  saveConfig(paths.configFile, config);
  return config;
}

function context(folders: UserFolders): ServiceContext {
  return { layout, paths, folders, ports, localUserId: config.localUserId, appVersion: app.getVersion() };
}

function getCore(ctx: ServiceContext): Core {
  if (!core) {
    core = new Core(ctx, log);
    core.on("change", () => {
      void refreshTray();
      sendToPortal(PORTAL_CHANNELS.servicesChanged, servicesStatus());
    });
  } else core.setContext(ctx);
  return core;
}

function openLogs(): void {
  void shell.openPath(paths.logsDir);
}

function openSetupWindow(): BrowserWindow {
  if (setupWindow) return setupWindow;
  setupWindow = new BrowserWindow({
    width: 760,
    height: 640,
    minWidth: 600,
    minHeight: 560,
    title: "Sauri",
    show: false,
    backgroundColor: "#faf9fe",
    webPreferences: {
      preload: path.join(DIST, "setup-preload.cjs"),
      contextIsolation: true,
      sandbox: true,
      nodeIntegration: false,
    },
  });
  setupWindow.webContents.on("will-navigate", (event) => event.preventDefault());
  setupWindow.webContents.setWindowOpenHandler(() => ({ action: "deny" }));
  setupWindow.once("ready-to-show", () => {
    if (!quietStartup) setupWindow?.show();
  });
  setupWindow.on("close", (event) => {
    // Closing setup or an error screen quits; during startup it only hides.
    if (!quitting && started) {
      event.preventDefault();
      setupWindow?.hide();
    } else if (!quitting && !started) {
      event.preventDefault();
      app.quit();
    }
  });
  setupWindow.on("closed", () => {
    setupWindow = null;
  });
  void setupWindow.loadFile(path.join(DIST, "setup", "index.html"));
  return setupWindow;
}

function portalUrl(): string {
  return `http://localhost:${ports.api}/`;
}

/** Phase B of the first run (models and extension) lives in the portal until it marks setup done. */
function portalStartUrl(): string {
  return config.setupStep === "done" ? portalUrl() : `${portalUrl()}bienvenida`;
}

function fromPortal(event: IpcMainInvokeEvent): boolean {
  const url = event.senderFrame?.url;
  return Boolean(url && portalWindow && event.sender === portalWindow.webContents && new URL(url).origin === new URL(portalUrl()).origin);
}

function confirm(target: BrowserWindow | null, options: Electron.MessageBoxOptions): Promise<Electron.MessageBoxReturnValue> {
  return target ? dialog.showMessageBox(target, options) : dialog.showMessageBox(options);
}

let relocating = false;

/** The portal window in front of everything, so a sheet attached to it is seen at once (macOS can leave it behind). */
function bringPortalToFront(): BrowserWindow | null {
  if (!portalWindow || portalWindow.isDestroyed()) return null;
  if (portalWindow.isMinimized()) portalWindow.restore();
  portalWindow.show();
  if (process.platform === "darwin") app.focus({ steal: true });
  portalWindow.focus();
  return portalWindow;
}

/** Sends an event to the portal window, and only while it shows the portal's own origin. */
function sendToPortal(channel: string, payload: unknown): void {
  const contents = portalWindow && !portalWindow.isDestroyed() ? portalWindow.webContents : null;
  if (!contents || contents.isDestroyed()) return;
  const url = contents.getURL();
  if (!url || new URL(url).origin !== new URL(portalUrl()).origin) return;
  contents.send(channel, payload);
}

function servicesStatus(): ServicesStatus {
  return core?.portalStatus() ?? { starting: false, problem: false };
}

/** «Cambiar» on the storage page: the whole move runs here, the portal only waits for the result. */
async function relocateFolder(kind: FolderKind): Promise<RelocateResult> {
  if (relocating) return { ok: false, reason: "busy" };
  relocating = true;
  try {
    return await relocate(kind, {
      config: () => config,
      update,
      processing: processingCount,
      chooseFolder: async (which) => {
        const options: Electron.OpenDialogOptions = {
          title: t(locale(), `folder.${which}` as MessageKey),
          properties: ["openDirectory", "createDirectory"],
        };
        // A sheet on the portal window: it cannot end up behind it.
        const parent = bringPortalToFront();
        const result = parent ? await dialog.showOpenDialog(parent, options) : await dialog.showOpenDialog(options);
        return result.canceled ? null : (result.filePaths[0] ?? null);
      },
      confirmTrash: async (which, previous) => {
        const kindName = t(locale(), `folder.${which}` as MessageKey).toLowerCase();
        const offer = await confirm(bringPortalToFront(), {
          type: "question",
          message: t(locale(), "relocate.done.title", { kind: kindName }),
          detail: t(locale(), "relocate.done.detail", { path: previous }),
          buttons: [t(locale(), "relocate.keep"), t(locale(), "relocate.trash")],
          defaultId: 0,
          cancelId: 0,
        });
        if (offer.response !== 1) return false;
        const sure = await confirm(portalWindow, {
          type: "warning",
          message: t(locale(), "relocate.confirm.title", { path: previous }),
          detail: t(locale(), "relocate.confirm.detail"),
          buttons: [t(locale(), "relocate.cancel"), t(locale(), "relocate.trash")],
          defaultId: 0,
          cancelId: 0,
        });
        return sure.response === 1;
      },
      trash: (dir) => shell.trashItem(dir),
      stopServices: async () => {
        clearInterval(poll);
        started = false;
        await core?.stop();
      },
      startServices,
      log: (line) => log.line(line),
      progress: (progress) => sendToPortal(PORTAL_CHANNELS.relocateProgress, progress),
    });
  } finally {
    relocating = false;
  }
}

/** What applying an update does to this app (design D12); the order and the rollback live in updater.ts. */
function updateDeps(): Omit<ApplyDeps, "log"> {
  const folders = () => config.paths as UserFolders;
  return {
    processing: processingCount,
    stopServices: async () => {
      clearInterval(poll);
      started = false;
      await core?.stop();
    },
    startDatabase: async () => {
      await getCore(context(folders())).startDatabase();
    },
    stopDatabase: async () => {
      await core?.stop();
    },
    migrate: async (stagedApp) => {
      try {
        await prepareDatabase({ ...context(folders()), layout: bundleLayout(stagedApp) }, log);
        return true;
      } catch (error) {
        log.line(`update migration: ${error instanceof Error ? error.message : String(error)}`);
        return false;
      }
    },
    restartServices: startServices,
    swap: swapBundle,
    applied: (version) => {
      update({ appVersionOfData: version });
      fs.rmSync(paths.updatesDir, { recursive: true, force: true });
    },
    relaunch: () => {
      quitting = true;
      updater?.stop();
      tray?.destroy();
      log.close();
      app.relaunch({ execPath: process.execPath, args: process.argv.slice(1) });
      app.exit(0);
    },
  };
}

function createUpdater(): UpdateController {
  return new UpdateController({
    currentVersion: app.getVersion(),
    // Development builds never update themselves; the installed app needs a download place (design D13).
    source: app.isPackaged ? releaseSource() : null,
    updatesDir: paths.updatesDir,
    databaseDir: () => config.paths?.database ?? null,
    bundle: () => appBundleOf(process.execPath, app.isPackaged),
    autoCheck: () => config.autoUpdate,
    saveAutoCheck: (on) => update({ autoUpdate: on }),
    locale,
    deps: updateDeps,
    log: (line) => log.line(line),
    onChange: () => {
      setAppMenu();
      tray?.refresh();
      if (updater) sendToPortal(PORTAL_CHANNELS.updateChanged, updater.status());
    },
  });
}

function registerPortalApi(): void {
  const handle = (channel: string, listener: (...args: unknown[]) => unknown) => {
    ipcMain.removeHandler(channel);
    ipcMain.handle(channel, (event, ...args) => {
      if (!fromPortal(event)) throw new Error("forbidden");
      return listener(...args);
    });
  };
  handle(PORTAL_CHANNELS.getPaths, () => (config.paths ? folderUsage(config.paths) : []));
  handle(PORTAL_CHANNELS.relocate, (kind) => {
    if (!FOLDER_KINDS.includes(kind as FolderKind)) throw new Error("invalid_kind");
    return relocateFolder(kind as FolderKind);
  });
  handle(PORTAL_CHANNELS.getLocale, () => locale());
  handle(PORTAL_CHANNELS.updateStatus, () => updater?.status());
  handle(PORTAL_CHANNELS.updateCheck, () => updater?.check());
  // The portal's «Reiniciar y actualizar» button is the person's confirmation.
  handle(PORTAL_CHANNELS.updateApply, () => updater?.apply());
  handle(PORTAL_CHANNELS.updateAutoCheck, (on) => updater?.setAutoCheck(on === true));
  handle(PORTAL_CHANNELS.servicesStatus, () => servicesStatus());
  handle(PORTAL_CHANNELS.markSetupDone, () => {
    if (phaseADone(config) && config.setupStep !== "done") {
      update({ setupStep: "done" });
      log.line("setup phase B finished");
    }
  });
}

function openPortalWindow(): void {
  if (portalWindow) {
    portalWindow.show();
    portalWindow.focus();
    return;
  }
  const origin = new URL(portalUrl()).origin;
  portalWindow = new BrowserWindow({
    width: 1360,
    height: 880,
    minWidth: 960,
    minHeight: 600,
    title: "Sauri",
    backgroundColor: "#faf9fe",
    webPreferences: {
      preload: path.join(DIST, "portal-preload.cjs"),
      contextIsolation: true,
      sandbox: true,
      nodeIntegration: false,
    },
  });
  // The portal stays on its own origin; any other link opens in the default browser.
  portalWindow.webContents.on("will-navigate", (event, url) => {
    if (new URL(url).origin !== origin) {
      event.preventDefault();
      if (/^https?:/.test(url)) void shell.openExternal(url);
    }
  });
  portalWindow.webContents.setWindowOpenHandler(({ url }) => {
    if (/^https?:/.test(url)) void shell.openExternal(url);
    return { action: "deny" };
  });
  portalWindow.on("close", (event) => {
    if (quitting) return;
    event.preventDefault();
    portalWindow?.hide();
  });
  portalWindow.on("closed", () => {
    portalWindow = null;
  });
  void portalWindow.loadURL(portalStartUrl());
}

function showMain(): void {
  if (started) openPortalWindow();
  else openSetupWindow().show();
}

async function processingCount(): Promise<number | null> {
  if (!started) return null;
  try {
    const status = await fetchLocalStatus(ports.api, readSecret(paths, "local_token"));
    return status ? status.processing : null;
  } catch {
    return null;
  }
}

async function refreshTray(): Promise<void> {
  if (!tray) return;
  const processing = await processingCount();
  tray.update(trayStatus(locale(), core?.summary() ?? [], processing, started));
}

function showError(message: string, canRetry = true): void {
  log.line(`startup stopped: ${message}`);
  quietStartup = false;
  controller?.show({ view: "error", message, canRetry });
  openSetupWindow().show();
}

/** Folders, ports, then services in the order of the startup diagram. Errors stop before anything half-starts. */
async function startServices(): Promise<void> {
  const folders = config.paths as UserFolders;
  const missing = folderProblems(folders, config.installId);
  if (missing.length > 0) {
    const problem = missing[0];
    const kind = t(locale(), `folder.${problem.kind}`).toLowerCase();
    return showError(t(locale(), `error.folder.${problem.reason}`, { kind, path: problem.path }));
  }
  const busy = await busyPorts(portsToCheck(ports));
  if (busy.length > 0) return showError(t(locale(), "error.ports", { ports: busy.join(", ") }));
  try {
    socketPath(paths.runDir, PG_SOCKET_PORT);
  } catch (error) {
    if (error instanceof PathError) return showError(t(locale(), "error.socket_path_too_long", { path: error.detail }), false);
    throw error;
  }
  ensureSecrets(paths);
  const services = getCore(context(folders));
  controller?.show({ view: "progress", key: "startup.database" });
  // Requirement 9.3: a copy of the database before any migration a new app version brings.
  const migration = await migrateOnStart({
    databaseDir: folders.database,
    dataVersion: config.appVersionOfData,
    appVersion: app.getVersion(),
    databaseRunning: services.databaseRunning,
    startDatabase: () => services.startDatabase(),
    stopDatabase: () => services.stop(),
    migrate: async () => {
      try {
        await prepareDatabase(context(folders), log);
        return true;
      } catch (error) {
        log.line(`startup migration: ${error instanceof Error ? error.message : String(error)}`);
        return false;
      }
    },
    log: (line) => log.line(line),
  });
  if (!migration.ok) {
    await services.stop();
    core = undefined;
    return showError(t(locale(), migration.restored ? "error.migration.restored" : "error.migration", { code: migration.reason }));
  }
  if (config.appVersionOfData !== app.getVersion()) update({ appVersionOfData: app.getVersion() });
  try {
    controller?.show({ view: "progress", key: "startup.core" });
    await services.startApi({ migrated: true });
  } catch (error) {
    const code = error instanceof CoreError ? error.code : "unexpected";
    log.line(`startup failed: ${error instanceof Error ? error.message : String(error)}`);
    await services.stop();
    core = undefined;
    return showError(t(locale(), "error.start", { code }));
  }
  // The window opens as soon as the API answers; the portal shows that the engines are still starting.
  started = true;
  openPortalWindow();
  setupWindow?.hide();
  clearInterval(poll);
  poll = setInterval(() => {
    void refreshTray();
    // Engines waiting for a model or the speaker runtime start as soon as setup phase B installs it.
    void services.startWaitingEngines();
  }, 5000);
  await refreshTray();
  // Never throws: a service that does not come up shows in the tray and the portal, and keeps being retried.
  await services.startBackground();
  log.line(`services: ${JSON.stringify(services.summary())}`);
  await refreshTray();
}

/** Stops every service; asks first when meetings are being processed (Requirement 8.4). */
async function quitFlow(ask: boolean): Promise<void> {
  if (quitting) return;
  if (ask) {
    const processing = await processingCount();
    if (processing && processing > 0) {
      const target = portalWindow ?? setupWindow;
      const options: Electron.MessageBoxOptions = {
        type: "warning",
        message: t(locale(), "quit.title"),
        detail: plural(locale(), "quit.message", processing),
        buttons: [t(locale(), "quit.wait"), t(locale(), "quit.anyway")],
        defaultId: 0,
        cancelId: 0,
      };
      const answer = target ? await dialog.showMessageBox(target, options) : await dialog.showMessageBox(options);
      if (answer.response === 0) return;
    }
  }
  quitting = true;
  clearInterval(poll);
  updater?.stop();
  log.line("quitting");
  await core?.stop();
  tray?.destroy();
  log.close();
  app.exit(0);
}

function megabytes(bytes: number): string {
  return bytes >= 1e9 ? formatGigabytes(locale(), bytes) : `${Math.round(bytes / 1e6)} MB`;
}

function uninstallPlan(): UninstallPlan {
  return planUninstall({
    paths,
    folders: config.paths as UserFolders | undefined,
    installId: config.installId,
    appId: dev ? undefined : APP_ID,
    appBundle: appBundleOf(process.execPath, app.isPackaged),
  });
}

async function ask(options: Electron.MessageBoxOptions): Promise<Electron.MessageBoxReturnValue> {
  const target = portalWindow?.isVisible() ? portalWindow : setupWindow?.isVisible() ? setupWindow : null;
  return target ? dialog.showMessageBox(target, options) : dialog.showMessageBox(options);
}

function folderLine(folder: FolderTarget): string {
  const kind = t(locale(), `folder.${folder.kind}`);
  if (folder.verdict === "ok") return t(locale(), "uninstall.folders.item", { kind, path: folder.path, size: megabytes(folder.bytes) });
  return t(locale(), "uninstall.folders.itemKept", {
    kind,
    path: folder.path,
    reason: t(locale(), `uninstall.reason.${folder.verdict}`),
  });
}

function uninstallSummary(report: UninstallReport, appLeft: string | null): string {
  const lines = [t(locale(), "uninstall.done.internal")];
  lines.push(t(locale(), report.trashed.length > 0 ? "uninstall.done.foldersTrashed" : "uninstall.done.foldersKept"));
  if (appLeft) lines.push(t(locale(), "uninstall.done.appLeft", { path: appLeft }));
  if (report.failed.length > 0) lines.push(t(locale(), "uninstall.done.failed", { paths: report.failed.map((item) => item.path).join(", ") }));
  return lines.join("\n\n");
}

/** Settings action "Uninstall Sauri" (Requirement 10); every question defaults to the safe answer. */
async function uninstallFlow(): Promise<void> {
  if (quitting) return;
  const report = await runUninstall({
    plan: uninstallPlan,
    processing: processingCount,
    confirm: async (plan) => {
      const bytes = plan.internal.reduce((sum, item) => sum + item.bytes, 0);
      const bundle = plan.appBundle;
      const detail = [t(locale(), "uninstall.message", { size: megabytes(bytes) })];
      if (bundle && !bundle.writable) detail.push(t(locale(), "uninstall.appNotWritable", { path: bundle.path }));
      const answer = await ask({
        type: "warning",
        message: t(locale(), "uninstall.title"),
        detail: detail.join("\n\n"),
        buttons: [t(locale(), "uninstall.cancel"), t(locale(), "uninstall.confirm")],
        defaultId: 0,
        cancelId: 0,
        ...(bundle?.writable ? { checkboxLabel: t(locale(), "uninstall.removeApp"), checkboxChecked: true } : {}),
      });
      return { proceed: answer.response === 1, removeApp: answer.checkboxChecked };
    },
    confirmProcessing: async (count) => {
      const answer = await ask({
        type: "warning",
        message: t(locale(), "quit.title"),
        detail: plural(locale(), "uninstall.processing", count),
        buttons: [t(locale(), "quit.wait"), t(locale(), "uninstall.anyway")],
        defaultId: 0,
        cancelId: 0,
      });
      return answer.response === 1;
    },
    trashFolders: async (folders) => {
      const answer = await ask({
        type: "question",
        message: t(locale(), "uninstall.folders.title"),
        detail: `${t(locale(), "uninstall.folders.message")}\n\n${folders.map(folderLine).join("\n")}`,
        buttons: [t(locale(), "uninstall.folders.keep"), t(locale(), "uninstall.folders.trash")],
        defaultId: 0,
        cancelId: 0,
      });
      return answer.response === 1;
    },
    stopServices: async () => {
      quitting = true;
      clearInterval(poll);
      log.line("uninstalling: stopping services");
      await core?.stop();
      setLaunchAtLogin(false);
      tray?.destroy();
      log.close();
    },
    trash: (target) => shell.trashItem(target),
  });
  if (!report) return;
  const bundle = appBundleOf(process.execPath, app.isPackaged);
  const appLeft = bundle && !report.appRemoved ? bundle.path : null;
  await dialog.showMessageBox({
    type: "info",
    message: t(locale(), "uninstall.done.title"),
    detail: uninstallSummary(report, appLeft),
    buttons: [t(locale(), "uninstall.done.close")],
  });
  // Electron may write its profile and logs again while it exits: remove them once more after the exit.
  const sweep = afterExitSweep(process.pid, internalPaths(paths, dev ? undefined : APP_ID));
  spawn(sweep.command, sweep.args, { detached: true, stdio: "ignore" }).unref();
  app.exit(0);
}

function setAppMenu(): void {
  Menu.setApplicationMenu(
    Menu.buildFromTemplate([
      {
        label: app.name,
        submenu: [
          { role: "about" },
          ...(updater?.menuItems() ?? []),
          { type: "separator" },
          { label: t(locale(), "menu.uninstall"), click: () => void uninstallFlow() },
          { type: "separator" },
          { role: "hide" },
          { role: "hideOthers" },
          { role: "unhide" },
          { type: "separator" },
          { role: "quit" },
        ],
      },
      { role: "editMenu" },
      { role: "viewMenu" },
      { role: "windowMenu" },
    ]),
  );
}

async function retry(): Promise<void> {
  config = loadConfig(paths.configFile);
  await startServices();
}

app.on("second-instance", () => showMain());
app.on("activate", () => showMain());
app.on("window-all-closed", () => {
  // The services keep running from the menu bar.
});
app.on("before-quit", (event) => {
  if (quitting) return;
  event.preventDefault();
  void quitFlow(true);
});
for (const sig of ["SIGINT", "SIGTERM"] as const) process.on(sig, () => void quitFlow(false));
// An error nothing caught goes to desktop.log instead of a blocking dialog that stops every service and window.
process.on("uncaughtException", (error) => log.line(`uncaught error: ${error.stack ?? String(error)}`));
process.on("unhandledRejection", (reason) =>
  log.line(`unhandled rejection: ${reason instanceof Error ? (reason.stack ?? reason.message) : String(reason)}`),
);

app.whenReady().then(async () => {
  if (!single) return;
  log.line(`Sauri desktop ${app.getVersion()} (${dev ? "development" : "installed"}), data in ${paths.dataDir}`);
  try {
    config = loadConfig(paths.configFile);
  } catch (error) {
    const code = error instanceof ConfigError ? error.code : "config_unreadable";
    await dialog.showMessageBox({ type: "error", message: t("es", "error.title"), detail: t("es", "error.config", { code }) });
    app.exit(1);
    return;
  }
  saveConfig(paths.configFile, config);
  setLaunchAtLogin(config.launchAtLogin);
  updater = createUpdater();
  setAppMenu();
  tray = new SauriTray(locale(), {
    open: showMain,
    openLogs,
    uninstall: () => void uninstallFlow(),
    quit: () => app.quit(),
    launchAtLogin: () => config.launchAtLogin,
    toggleLaunchAtLogin: (on) => {
      update({ launchAtLogin: on });
      setLaunchAtLogin(on);
    },
    updateItems: () => updater?.menuItems() ?? [],
  });
  updater.start();
  registerPortalApi();
  controller = new SetupController({
    paths,
    layout,
    config: () => config,
    update,
    context,
    core: getCore,
    log,
    window: () => setupWindow,
    onLocale: (value) => {
      tray?.setLocale(value);
      setAppMenu();
    },
    retry: () => void retry(),
    openLogs,
    quit: () => app.quit(),
  });
  quietStartup = phaseADone(config);
  openSetupWindow();
  if (!phaseADone(config)) {
    await controller.done;
    // Setup phase A just created and migrated this data with this version: no copy is due on this start.
    update({ appVersionOfData: app.getVersion() });
  }
  controller.mode = "startup";
  await startServices();
});
