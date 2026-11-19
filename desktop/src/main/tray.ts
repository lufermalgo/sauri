// Menu-bar icon (Requirement 8.2): the Sauri isotype in four states told apart by shape (template images are
// monochrome; see tray-icon.ts) and by the status line of its menu.
import { Menu, type MenuItemConstructorOptions, nativeImage, Tray } from "electron";
import { type Locale, plural, t } from "../i18n.ts";
import type { ServiceSummary } from "./services.ts";
import { ICON_SIZE, iconPixels } from "./tray-icon.ts";

export type TrayState = "starting" | "ready" | "processing" | "error";

export interface TrayStatus {
  state: TrayState;
  label: string;
}

/** What the icon says, from the services and the API's processing count (null: the API did not answer). */
export function trayStatus(
  locale: Locale,
  summary: ServiceSummary[],
  processing: number | null,
  started: boolean,
): TrayStatus {
  const failed = summary.filter((item) => "failed" in item && item.failed).map((item) => item.name);
  if (failed.length > 0) return { state: "error", label: t(locale, "tray.status.error", { names: failed.join(", ") }) };
  if (!started) return { state: "starting", label: t(locale, "tray.status.starting") };
  if (processing === null) return { state: "error", label: t(locale, "tray.status.error", { names: "api" }) };
  const waiting = summary.filter((item) => "blocked" in item).map((item) => item.name);
  const suffix = waiting.length > 0 ? ` · ${t(locale, "tray.status.waiting", { names: waiting.join(", ") })}` : "";
  if (processing > 0) return { state: "processing", label: plural(locale, "tray.status.processing", processing) + suffix };
  return { state: "ready", label: t(locale, "tray.status.ready") + suffix };
}

function icon(state: TrayState): Electron.NativeImage {
  const image = nativeImage.createFromBitmap(iconPixels(state), { width: ICON_SIZE, height: ICON_SIZE, scaleFactor: 2 });
  image.setTemplateImage(true);
  return image;
}

export interface TrayActions {
  open: () => void;
  /** The portal address, shown as a line that does nothing when clicked. */
  portalUrl: () => string;
  openLogs: () => void;
  uninstall: () => void;
  quit: () => void;
  launchAtLogin: () => boolean;
  toggleLaunchAtLogin: (on: boolean) => void;
  /** The updater's entries (check, restart and update, automatic checks); empty while it is off. */
  updateItems?: () => MenuItemConstructorOptions[];
}

export class SauriTray {
  private readonly tray: Tray;
  private status: TrayStatus;

  constructor(
    private locale: Locale,
    private readonly actions: TrayActions,
  ) {
    this.status = { state: "starting", label: t(locale, "tray.status.starting") };
    this.tray = new Tray(icon("starting"));
    this.tray.on("double-click", () => actions.open());
    this.render();
  }

  setLocale(locale: Locale): void {
    this.locale = locale;
    this.render();
  }

  update(status: TrayStatus): void {
    if (status.state === this.status.state && status.label === this.status.label) return;
    if (status.state !== this.status.state) this.tray.setImage(icon(status.state));
    this.status = status;
    this.render();
  }

  /** Rebuilds the menu (after the updater changed state). */
  refresh(): void {
    this.render();
  }

  private render(): void {
    const { locale, actions } = this;
    this.tray.setToolTip(`Sauri · ${this.status.label}`);
    this.tray.setContextMenu(
      Menu.buildFromTemplate([
        { label: this.status.label, enabled: false },
        { label: actions.portalUrl(), enabled: false },
        { type: "separator" },
        { label: t(locale, "tray.open"), click: actions.open },
        { label: t(locale, "tray.logs"), click: actions.openLogs },
        {
          label: t(locale, "tray.launchAtLogin"),
          type: "checkbox",
          checked: actions.launchAtLogin(),
          click: (item) => actions.toggleLaunchAtLogin(item.checked),
        },
        ...(actions.updateItems?.() ?? []),
        { type: "separator" },
        { label: t(locale, "menu.uninstall"), click: actions.uninstall },
        { label: t(locale, "tray.quit"), click: actions.quit },
      ]),
    );
  }

  destroy(): void {
    this.tray.destroy();
  }
}
