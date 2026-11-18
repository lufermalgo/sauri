// The contract between the portal window (the web portal, untrusted for Node access), its preload and the main
// process. The portal declares the same shape in `frontend/src/desktop-bridge.ts`.
import type { FolderKind } from "./folders.ts";

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

export interface PortalUpdatesApi {
  status(): Promise<UpdateStatus>;
  check(): Promise<UpdateStatus>;
  /** The button itself is the confirmation: stops the services, migrates, swaps the app and relaunches. */
  apply(): Promise<UpdateStatus>;
  setAutoCheck(on: boolean): Promise<UpdateStatus>;
}

export interface PortalDesktopApi {
  getPaths(): Promise<FolderUsage[]>;
  relocate(kind: FolderKind): Promise<RelocateResult>;
  markSetupDone(): Promise<void>;
  /** The language chosen in the app's setup; the portal starts in it unless the person picked another there. */
  getLocale(): Promise<"es" | "en">;
  updates: PortalUpdatesApi;
}

export const PORTAL_CHANNELS = {
  getPaths: "portal:get-paths",
  relocate: "portal:relocate",
  markSetupDone: "portal:mark-setup-done",
  getLocale: "portal:get-locale",
  updateStatus: "portal:update-status",
  updateCheck: "portal:update-check",
  updateApply: "portal:update-apply",
  updateAutoCheck: "portal:update-auto-check",
} as const;
