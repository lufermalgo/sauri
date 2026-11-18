// Menu-bar icon (Requirement 8.2): ready, processing or error, told apart by shape (template images are
// monochrome) and by the status line of its menu.
import { Menu, nativeImage, Tray } from "electron";
import { type Locale, plural, t } from "../i18n.ts";
import type { ServiceSummary } from "./services.ts";

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

const SIZE = 32; // 16 pt at 2x

/** Black-on-transparent BGRA pixels: dot (ready), ring (processing/starting), dot with a gap (error). */
export function iconPixels(state: TrayState): Buffer {
  const pixels = Buffer.alloc(SIZE * SIZE * 4);
  const center = (SIZE - 1) / 2;
  for (let y = 0; y < SIZE; y += 1) {
    for (let x = 0; x < SIZE; x += 1) {
      const distance = Math.hypot(x - center, y - center);
      let on = false;
      if (state === "ready") on = distance <= 11;
      else if (state === "error") on = distance <= 11 && !(Math.abs(x - center) <= 2 && (y < 10 || (y > 18 && y < 22)));
      else on = (distance <= 11 && distance >= 8) || (state === "processing" && distance <= 4);
      if (on) pixels[(y * SIZE + x) * 4 + 3] = 255;
    }
  }
  return pixels;
}

function icon(state: TrayState): Electron.NativeImage {
  const image = nativeImage.createFromBitmap(iconPixels(state), { width: SIZE, height: SIZE, scaleFactor: 2 });
  image.setTemplateImage(true);
  return image;
}

export interface TrayActions {
  open: () => void;
  openLogs: () => void;
  quit: () => void;
  launchAtLogin: () => boolean;
  toggleLaunchAtLogin: (on: boolean) => void;
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

  private render(): void {
    const { locale, actions } = this;
    this.tray.setToolTip(`Sauri · ${this.status.label}`);
    this.tray.setContextMenu(
      Menu.buildFromTemplate([
        { label: this.status.label, enabled: false },
        { type: "separator" },
        { label: t(locale, "tray.open"), click: actions.open },
        { label: t(locale, "tray.logs"), click: actions.openLogs },
        {
          label: t(locale, "tray.launchAtLogin"),
          type: "checkbox",
          checked: actions.launchAtLogin(),
          click: (item) => actions.toggleLaunchAtLogin(item.checked),
        },
        { type: "separator" },
        { label: t(locale, "tray.quit"), click: actions.quit },
      ]),
    );
  }

  destroy(): void {
    this.tray.destroy();
  }
}
