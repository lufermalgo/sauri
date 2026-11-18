/**
 * What the Sauri desktop app exposes to the portal through its preload (`desktop/src/preload.ts`, contract in
 * `desktop/src/shared/portal-api.ts`). In a normal browser there is no bridge and these features say so.
 */
export type FolderKind = "recordings" | "database" | "models";
export const FOLDER_KINDS: readonly FolderKind[] = ["recordings", "database", "models"];

export interface FolderUsage {
  kind: FolderKind;
  path: string;
  usedBytes: number | null;
  freeBytes: number | null;
}

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

/** Where the app's updater stands (desktop `shared/portal-api.ts`, design D12). */
export type UpdateState = "disabled" | "idle" | "checking" | "downloading" | "up_to_date" | "ready" | "applying" | "error";

export interface UpdateStatus {
  state: UpdateState;
  current: string;
  version?: string;
  percent?: number;
  error?: string;
  count?: number;
  manualZip?: string;
  autoCheck: boolean;
  lastCheck?: string;
}

export interface DesktopUpdates {
  status(): Promise<UpdateStatus>;
  check(): Promise<UpdateStatus>;
  /** The button is the person's confirmation: the app stops, migrates the data, swaps itself and opens again. */
  apply(): Promise<UpdateStatus>;
  setAutoCheck(on: boolean): Promise<UpdateStatus>;
}

export interface SauriDesktop {
  getPaths(): Promise<FolderUsage[]>;
  relocate(kind: FolderKind): Promise<RelocateResult>;
  markSetupDone(): Promise<void>;
  /** The language chosen in the app's setup. Missing in older app versions. */
  getLocale?(): Promise<string>;
  /** Missing in app versions older than the updater. */
  updates?: DesktopUpdates;
}

declare global {
  interface Window {
    sauriDesktop?: SauriDesktop;
  }
}

/** The desktop app's bridge, or null in a normal browser. */
export function desktopBridge(): SauriDesktop | null {
  return typeof window !== "undefined" && window.sauriDesktop ? window.sauriDesktop : null;
}
