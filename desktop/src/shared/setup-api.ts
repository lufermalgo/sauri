// The contract between the setup window (renderer), its preload and the main process.
import type { Locale, MessageKey } from "../i18n.ts";
import type { HardwareReport } from "../main/hardware.ts";
import type { FolderKind, UserFolders } from "./folders.ts";

export type FolderIssue = "not_writable" | "not_a_directory" | "foreign" | "duplicate" | "unavailable";

export interface FolderInfo {
  kind: FolderKind;
  path: string;
  freeBytes: number | null;
  issue?: FolderIssue;
}

export interface SetupState {
  /** `setup`: phase A is pending; `startup`: the core is starting (progress and errors only). */
  mode: "setup" | "startup";
  step: "identity" | "folders";
  locale: Locale;
  name: string;
  folders: UserFolders;
  /** The last progress or error view, for a window that loads after it was sent. */
  view?: View;
}

export type View =
  | { view: "progress"; key: MessageKey }
  | { view: "error"; message: string; canRetry: boolean };

export type FinishResult = { ok: true } | { ok: false; folders?: FolderInfo[]; message?: string };

export interface SetupApi {
  state(): Promise<SetupState>;
  hardware(): Promise<HardwareReport>;
  setLocale(locale: Locale): Promise<void>;
  saveName(name: string): Promise<{ ok: boolean; error?: "empty" | "long" }>;
  back(): Promise<void>;
  inspect(folders: UserFolders): Promise<FolderInfo[]>;
  choose(kind: FolderKind): Promise<string | null>;
  finish(folders: UserFolders): Promise<FinishResult>;
  retry(): Promise<void>;
  openLogs(): Promise<void>;
  quit(): Promise<void>;
  onView(listener: (view: View) => void): void;
}

export const CHANNELS = {
  state: "setup:state",
  hardware: "setup:hardware",
  locale: "setup:locale",
  identity: "setup:identity",
  back: "setup:back",
  inspect: "setup:inspect",
  choose: "setup:choose",
  finish: "setup:finish",
  retry: "app:retry",
  logs: "app:logs",
  quit: "app:quit",
  view: "app:view",
} as const;

export const MAX_NAME_LENGTH = 255;

export function validateName(raw: unknown): { ok: true; name: string } | { ok: false; error: "empty" | "long" } {
  const name = typeof raw === "string" ? raw.trim() : "";
  if (!name) return { ok: false, error: "empty" };
  if (name.length > MAX_NAME_LENGTH) return { ok: false, error: "long" };
  return { ok: true, name };
}
