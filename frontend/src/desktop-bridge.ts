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

export interface SauriDesktop {
  getPaths(): Promise<FolderUsage[]>;
  relocate(kind: FolderKind): Promise<RelocateResult>;
  markSetupDone(): Promise<void>;
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
