// Sauri desktop: one instance, setup phase A when needed, then PostgreSQL, the API, the worker and the engines
// in order, the portal in its window and the menu-bar icon. Closing the window keeps the services running;
// quitting asks first when meetings are being processed.
import os from "node:os";
import path from "node:path";
import { spawn } from "node:child_process";
import { app, BrowserWindow, dialog, Menu, shell } from "electron";
import { formatGigabytes, type Locale, plural, t } from "../i18n.ts";
import { setLaunchAtLogin } from "./autostart.ts";
import { type AppConfig, ConfigError, loadConfig, phaseADone, saveConfig } from "./config.ts";
import { appPaths, folderProblems, PathError, socketPath, type UserFolders } from "./paths.ts";
import { busyPorts, DEFAULT_API_PORT, portPlan, portsToCheck } from "./ports.ts";
import { Core, CoreError, ensureSecrets, type Layout, PG_SOCKET_PORT, readSecret, type ServiceContext } from "./services.ts";
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
  if (!dev) {
    const resources = process.resourcesPath;
    return {
      runtimeDir: path.join(resources, "runtime"),
      sourceRoot: path.join(resources, "app-sources"),
      portalDir: path.join(resources, "portal"),
    };
  }
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
let portalWindow: BrowserWindow | null = null;
let controller: SetupController | undefined;
let started = false;
let quitting = false;
let poll: NodeJS.Timeout | undefined;

const locale = (): Locale => config?.locale ?? "es";

function update(change: Partial<AppConfig>): AppConfig {
  config = { ...config, ...change };
  saveConfig(paths.configFile, config);
  return config;
}

function context(folders: UserFolders): ServiceContext {
  return { layout, paths, folders, ports, localUserId: config.localUserId };
}

function getCore(ctx: ServiceContext): Core {
  if (!core) {
    core = new Core(ctx, log);
    core.on("change", () => void refreshTray());
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
  setupWindow.once("ready-to-show", () => setupWindow?.show());
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
    webPreferences: { contextIsolation: true, sandbox: true, nodeIntegration: false },
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
  void portalWindow.loadURL(portalUrl());
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
  try {
    controller?.show({ view: "progress", key: "startup.database" });
    await services.startDatabase();
    controller?.show({ view: "progress", key: "startup.core" });
    await services.startCore();
    controller?.show({ view: "progress", key: "startup.engines" });
    await services.startEngines();
  } catch (error) {
    const code = error instanceof CoreError ? error.code : "unexpected";
    log.line(`startup failed: ${error instanceof Error ? error.message : String(error)}`);
    await services.stop();
    core = undefined;
    return showError(t(locale(), "error.start", { code }));
  }
  started = true;
  log.line(`services: ${JSON.stringify(services.summary())}`);
  openPortalWindow();
  setupWindow?.hide();
  poll = setInterval(() => void refreshTray(), 5000);
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
  });
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
  openSetupWindow();
  if (!phaseADone(config)) await controller.done;
  controller.mode = "startup";
  await startServices();
});
