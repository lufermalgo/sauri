// The contract between the portal window (the web portal, untrusted for Node access), its preload and the main
// process. The portal declares the same shape in `frontend/src/desktop-bridge.ts`.
import { FOLDER_KINDS, type FolderKind } from "./folders.ts";

export interface FolderUsage {
  kind: FolderKind;
  path: string;
  usedBytes: number | null;
  freeBytes: number | null;
}

/** Why a move did not happen; `count` comes with `processing`, the byte figures with `no_space`. */
export type RelocateFailure =
  | "processing"
  | "status_unavailable"
  | "cancelled"
  | "busy"
  | "same"
  | "nested"
  | "not_empty"
  | "no_space"
  | "not_writable"
  | "not_a_directory"
  | "foreign"
  | "duplicate"
  | "unavailable"
  | "unsupported_file"
  | "copy_failed"
  | "verify_failed";

export type RelocateResult =
  | { ok: true; kind: FolderKind; path: string; previous: string; previousTrashed: boolean }
  | { ok: false; reason: RelocateFailure; count?: number; neededBytes?: number; freeBytes?: number; detail?: string };

/**
 * The step a move («Cambiar») is in, sent while it runs. `choosing`: the folder dialog is open; `confirm_trash`: the
 * question about the old folder is open; `restarting`: the services start again (on the new folder, or on the old
 * one after a failure). The final answer is the `relocate` result, not an event.
 */
export const RELOCATE_PHASES = [
  "choosing",
  "preparing",
  "copying",
  "verifying",
  "switching",
  "restarting",
  "confirm_trash",
  "trashing",
] as const;
export type RelocatePhase = (typeof RELOCATE_PHASES)[number];

/** `bytesDone`/`bytesTotal` come with `copying` and `verifying`. */
export interface RelocateProgress {
  kind: FolderKind;
  phase: RelocatePhase;
  bytesDone?: number;
  bytesTotal?: number;
}

function byteCount(value: unknown): number | undefined {
  return typeof value === "number" && Number.isFinite(value) && value >= 0 ? value : undefined;
}

/** A copy of a progress event with only the known fields, or null when it is not one (the preload's check). */
export function relocateProgressOf(value: unknown): RelocateProgress | null {
  if (typeof value !== "object" || value === null) return null;
  const { kind, phase, bytesDone, bytesTotal } = value as Record<string, unknown>;
  if (!FOLDER_KINDS.includes(kind as FolderKind) || !RELOCATE_PHASES.includes(phase as RelocatePhase)) return null;
  const progress: RelocateProgress = { kind: kind as FolderKind, phase: phase as RelocatePhase };
  const done = byteCount(bytesDone);
  const total = byteCount(bytesTotal);
  if (done !== undefined && total !== undefined) Object.assign(progress, { bytesDone: Math.min(done, total), bytesTotal: total });
  return progress;
}

/**
 * Where the updater stands (design D12). `disabled`: no download place yet or a development build; `ready`: a
 * verified version waits for «Reiniciar y actualizar».
 */
export type UpdateState = "disabled" | "idle" | "checking" | "downloading" | "up_to_date" | "ready" | "applying" | "error";

export interface UpdateStatus {
  state: UpdateState;
  current: string;
  /** The newer version found, downloading or ready. */
  version?: string;
  /** Download progress 0–100 while `downloading`. */
  percent?: number;
  /** Stable code of the last failure (a check, a download or an apply). */
  error?: string;
  /** Meetings in process when an apply was refused for that reason. */
  count?: number;
  /** The verified zip to install by hand when the app's folder is not writable. */
  manualZip?: string;
  autoCheck: boolean;
  lastCheck?: string;
}

const UPDATE_STATES: readonly UpdateState[] = ["disabled", "idle", "checking", "downloading", "up_to_date", "ready", "applying", "error"];

/** A copy of an update status event with only the known fields, or null when it is not one (the preload's check). */
export function updateStatusOf(value: unknown): UpdateStatus | null {
  if (typeof value !== "object" || value === null) return null;
  const { state, current, version, percent, error, count, manualZip, autoCheck, lastCheck } = value as Record<string, unknown>;
  if (!UPDATE_STATES.includes(state as UpdateState) || typeof current !== "string" || typeof autoCheck !== "boolean") return null;
  const status: UpdateStatus = { state: state as UpdateState, current, autoCheck };
  for (const [key, text] of Object.entries({ version, error, manualZip, lastCheck })) if (typeof text === "string") Object.assign(status, { [key]: text });
  for (const [key, number] of Object.entries({ percent, count })) {
    const checked = byteCount(number);
    if (checked !== undefined) Object.assign(status, { [key]: checked });
  }
  return status;
}

export interface PortalUpdatesApi {
  status(): Promise<UpdateStatus>;
  check(): Promise<UpdateStatus>;
  /** The button itself is the confirmation: stops the services, migrates, swaps the app and relaunches. */
  apply(): Promise<UpdateStatus>;
  setAutoCheck(on: boolean): Promise<UpdateStatus>;
  /** Calls `listener` each time the updater changes state (not for each download percent); returns the stop function. */
  onChange(listener: (status: UpdateStatus) => void): () => void;
}

/**
 * The services behind the portal. The window opens as soon as the API answers; `starting` stays true while the
 * engines and the worker are still on their first start (new meetings wait in the queue until then). `problem`: a
 * service did not start in time or keeps failing; the menu-bar icon says the same.
 */
export interface ServicesStatus {
  starting: boolean;
  problem: boolean;
}

/** A copy of a services status event, or null when it is not one (the preload's check). */
export function servicesStatusOf(value: unknown): ServicesStatus | null {
  if (typeof value !== "object" || value === null) return null;
  const { starting, problem } = value as Record<string, unknown>;
  if (typeof starting !== "boolean" || typeof problem !== "boolean") return null;
  return { starting, problem };
}

/**
 * How the portal window draws its title bar. `inset` (macOS): no title bar; the traffic lights sit over the portal's
 * own top bar, which leaves room for them and moves the window. `native`: the system's title bar, nothing to do.
 */
export type TitleBar = "inset" | "native";

/** The one place that decides it: main builds the window with it and the preload tells the portal before it paints. */
export function portalTitleBar(platform: string): TitleBar {
  return platform === "darwin" ? "inset" : "native";
}

/** The portal window's state the top bar follows: in native full screen macOS hides the traffic lights. */
export interface WindowState {
  fullScreen: boolean;
}

/** A copy of a window state event, or null when it is not one (the preload's check). */
export function windowStateOf(value: unknown): WindowState | null {
  if (typeof value !== "object" || value === null) return null;
  const { fullScreen } = value as Record<string, unknown>;
  return typeof fullScreen === "boolean" ? { fullScreen } : null;
}

export interface PortalDesktopApi {
  /** Known when the preload runs, so the portal's first paint already has the right top bar. */
  titleBar: TitleBar;
  getWindowState(): Promise<WindowState>;
  /** Calls `listener` when the window enters or leaves full screen; returns the function that stops listening. */
  onWindowState(listener: (state: WindowState) => void): () => void;
  getPaths(): Promise<FolderUsage[]>;
  relocate(kind: FolderKind): Promise<RelocateResult>;
  /** Calls `listener` with each step of a running move; returns the function that stops listening. */
  onRelocateProgress(listener: (progress: RelocateProgress) => void): () => void;
  markSetupDone(): Promise<void>;
  /** The language chosen in the app's setup; the portal starts in it unless the person picked another there. */
  getLocale(): Promise<"es" | "en">;
  updates: PortalUpdatesApi;
  getServicesStatus(): Promise<ServicesStatus>;
  /** Calls `listener` each time the services status changes; returns the function that stops listening. */
  onServicesStatus(listener: (status: ServicesStatus) => void): () => void;
}

export const PORTAL_CHANNELS = {
  getPaths: "portal:get-paths",
  relocate: "portal:relocate",
  /** Main process -> portal only, like `updateChanged`, `servicesChanged` and `windowChanged` (the channels the portal listens on). */
  relocateProgress: "portal:relocate-progress",
  updateChanged: "portal:update-changed",
  servicesStatus: "portal:services-status",
  servicesChanged: "portal:services-changed",
  windowState: "portal:window-state",
  windowChanged: "portal:window-changed",
  markSetupDone: "portal:mark-setup-done",
  getLocale: "portal:get-locale",
  updateStatus: "portal:update-status",
  updateCheck: "portal:update-check",
  updateApply: "portal:update-apply",
  updateAutoCheck: "portal:update-auto-check",
} as const;
