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

export interface PortalDesktopApi {
  getPaths(): Promise<FolderUsage[]>;
  relocate(kind: FolderKind): Promise<RelocateResult>;
  markSetupDone(): Promise<void>;
}

export const PORTAL_CHANNELS = {
  getPaths: "portal:get-paths",
  relocate: "portal:relocate",
  markSetupDone: "portal:mark-setup-done",
} as const;
