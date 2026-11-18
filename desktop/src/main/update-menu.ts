// The updater in the app: automatic checks every 6 hours (the settings switch turns them off), «Buscar
// actualizaciones…» and «Reiniciar y actualizar» in the menus and the portal, and the dialogs around them. The work
// itself lives in updater.ts.
import { dialog, type MenuItemConstructorOptions } from "electron";
import { type Locale, plural, t } from "../i18n.ts";
import type { UpdateStatus } from "../shared/portal-api.ts";
import type { ReleaseSource } from "./releases.ts";
import {
  type ApplyDeps,
  type AppBundleInfo,
  applyUpdate,
  CHECK_EVERY_MS,
  fetchFeed,
  FIRST_CHECK_DELAY_MS,
  pickRelease,
  readStaged,
  type Staged,
  stageRelease,
  UpdateError,
} from "./updater.ts";

export interface UpdateControllerOptions {
  currentVersion: string;
  /** Null while there is no download place, or in development: the updater stays off. */
  source: ReleaseSource | null;
  updatesDir: string;
  databaseDir: () => string | null;
  bundle: () => AppBundleInfo | null;
  autoCheck: () => boolean;
  saveAutoCheck: (on: boolean) => void;
  locale: () => Locale;
  deps: () => Omit<ApplyDeps, "log">;
  log: (line: string) => void;
  onChange: () => void;
  firstCheckDelayMs?: number;
}

export class UpdateController {
  private value: UpdateStatus;
  private staged: Staged | null = null;
  private timer: NodeJS.Timeout | undefined;
  private interval: NodeJS.Timeout | undefined;
  private busy: Promise<UpdateStatus> | null = null;

  constructor(private readonly opts: UpdateControllerOptions) {
    this.value = { state: opts.source ? "idle" : "disabled", current: opts.currentVersion, autoCheck: opts.autoCheck() };
    if (opts.source) {
      const staged = readStaged(opts.updatesDir);
      if (staged && staged.version !== opts.currentVersion) {
        this.staged = staged;
        this.value = { ...this.value, state: "ready", version: staged.version };
      }
    }
  }

  get enabled(): boolean {
    return this.opts.source !== null;
  }

  status(): UpdateStatus {
    return { ...this.value, autoCheck: this.opts.autoCheck() };
  }

  /** Menus are rebuilt only when the state changes, never for each download percent. */
  private set(change: Partial<UpdateStatus>): UpdateStatus {
    const before = this.value.state;
    this.value = { ...this.value, ...change, autoCheck: this.opts.autoCheck() };
    if (this.value.state !== before || change.autoCheck !== undefined || "error" in change) {
      try {
        this.opts.onChange();
      } catch (error) {
        this.opts.log(`update menu refresh failed: ${error instanceof Error ? error.message : String(error)}`);
      }
    }
    return this.status();
  }

  /** Schedules the automatic checks (when the switch is on); safe to call again after the switch changes. */
  start(): void {
    this.stop();
    if (!this.enabled || !this.opts.autoCheck()) return;
    this.timer = setTimeout(() => void this.check(), this.opts.firstCheckDelayMs ?? FIRST_CHECK_DELAY_MS);
    this.interval = setInterval(() => void this.check(), CHECK_EVERY_MS);
  }

  stop(): void {
    clearTimeout(this.timer);
    clearInterval(this.interval);
  }

  setAutoCheck(on: boolean): UpdateStatus {
    this.opts.saveAutoCheck(on);
    this.opts.log(`automatic update checks ${on ? "on" : "off"}`);
    this.start();
    return this.set({ autoCheck: on });
  }

  /** Looks for a newer version and, when there is one, downloads and checks it. One run at a time. */
  check(): Promise<UpdateStatus> {
    const source = this.opts.source;
    if (!source) return Promise.resolve(this.status());
    if (this.busy) return this.busy;
    if (this.value.state === "ready" || this.value.state === "applying") return Promise.resolve(this.status());
    this.busy = (async () => {
      this.set({ state: "checking", error: undefined, count: undefined });
      try {
        const release = pickRelease(await fetchFeed(source), this.opts.currentVersion);
        const lastCheck = new Date().toISOString();
        if (!release) return this.set({ state: "up_to_date", version: undefined, lastCheck });
        this.opts.log(`update ${release.version} found, downloading`);
        this.set({ state: "downloading", version: release.version, percent: 0, lastCheck });
        let shown = -1;
        this.staged = await stageRelease(source, release, this.opts.updatesDir, fetch, (done, total) => {
          const percent = Math.floor((done / total) * 100);
          if (percent !== shown) {
            shown = percent;
            this.set({ percent });
          }
        });
        this.opts.log(`update ${release.version} downloaded and verified`);
        return this.set({ state: "ready", version: release.version, percent: undefined });
      } catch (error) {
        const code = error instanceof UpdateError ? error.code : "check_failed";
        this.opts.log(`update check failed: ${error instanceof Error ? error.message : String(error)}`);
        return this.set({ state: "error", error: code, percent: undefined });
      } finally {
        this.busy = null;
      }
    })();
    return this.busy;
  }

  /** Applies the staged version (the caller has the person's confirmation). */
  async apply(): Promise<UpdateStatus> {
    const staged = this.staged;
    const databaseDir = this.opts.databaseDir();
    if (!staged || !databaseDir || this.value.state !== "ready") return this.status();
    this.set({ state: "applying", error: undefined, count: undefined, manualZip: undefined });
    const result = await applyUpdate({
      staged,
      bundle: this.opts.bundle(),
      databaseDir,
      fromVersion: this.opts.currentVersion,
      deps: { ...this.opts.deps(), log: this.opts.log },
    });
    if (result.ok) return this.set({ state: "applying" });
    return this.set({
      state: "ready",
      error: result.reason,
      count: result.count,
      manualZip: result.reason === "not_writable" ? staged.zipPath : undefined,
    });
  }

  // --- menus and dialogs --------------------------------------------------------------------------------

  menuItems(): MenuItemConstructorOptions[] {
    const locale = this.opts.locale();
    if (!this.enabled) return [];
    const items: MenuItemConstructorOptions[] = [];
    if (this.value.state === "ready" && this.value.version) {
      items.push({ label: t(locale, "update.menu.apply", { version: this.value.version }), click: () => void this.applyFromMenu() });
    } else {
      const working = this.value.state === "checking" || this.value.state === "downloading" || this.value.state === "applying";
      items.push({ label: t(locale, "update.menu.check"), enabled: !working, click: () => void this.checkFromMenu() });
    }
    items.push({
      label: t(locale, "update.menu.auto"),
      type: "checkbox",
      checked: this.opts.autoCheck(),
      click: (item) => this.setAutoCheck(item.checked),
    });
    return items;
  }

  private async checkFromMenu(): Promise<void> {
    const locale = this.opts.locale();
    const status = await this.check();
    if (status.state === "ready") return this.applyFromMenu();
    const message =
      status.state === "up_to_date"
        ? t(locale, "update.upToDate", { version: status.current })
        : t(locale, "update.checkFailed", { code: status.error ?? "check_failed" });
    await dialog.showMessageBox({ type: status.state === "error" ? "warning" : "info", message, buttons: [t(locale, "update.ok")] });
  }

  private async applyFromMenu(): Promise<void> {
    const locale = this.opts.locale();
    const version = this.value.version ?? "";
    const answer = await dialog.showMessageBox({
      type: "question",
      message: t(locale, "update.ready.title", { version }),
      detail: t(locale, "update.ready.detail"),
      buttons: [t(locale, "update.later"), t(locale, "update.restart")],
      defaultId: 1,
      cancelId: 0,
    });
    if (answer.response !== 1) return;
    const status = await this.apply();
    if (status.state === "ready" && status.error) await this.explainFailure(status);
  }

  /** Why an apply did not happen, in plain words. */
  async explainFailure(status: UpdateStatus): Promise<void> {
    const locale = this.opts.locale();
    let detail: string;
    if (status.error === "processing") detail = plural(locale, "update.failed.processing", status.count ?? 0);
    else if (status.error === "not_writable") detail = t(locale, "update.failed.not_writable", { path: status.manualZip ?? "" });
    else detail = t(locale, `update.failed.${status.error === "migration_failed" ? "migration_failed" : "generic"}`);
    await dialog.showMessageBox({ type: "warning", message: t(locale, "update.failed.title"), detail, buttons: [t(locale, "update.ok")] });
  }
}
