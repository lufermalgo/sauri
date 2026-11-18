// Internal paths (what the user never chooses) and user folders (recordings, database, models) with their
// `.sauri-folder` markers, so the core never starts on an empty or foreign folder.
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

import { FOLDER_KINDS, type FolderKind, type UserFolders } from "../shared/folders.ts";

export { FOLDER_KINDS, type FolderKind, type UserFolders };

export const MARKER_FILE = ".sauri-folder";
/** macOS `sun_path` holds 104 bytes including the final NUL. */
export const MAX_SOCKET_PATH_BYTES = 103;
/** The socket and the lock file PostgreSQL creates next to it. */
const SOCKET_LOCK_SUFFIX = ".lock";

export interface AppPaths {
  dev: boolean;
  home: string;
  dataDir: string;
  configFile: string;
  secretsDir: string;
  runDir: string;
  enginesDir: string;
  /** Downloadable components (the speaker runtime) once installed (design D9, D11). */
  componentsDir: string;
  /** Downloaded and verified app versions waiting to be applied (design D12). */
  updatesDir: string;
  cacheDir: string;
  electronDir: string;
  logsDir: string;
}

export class PathError extends Error {
  constructor(
    readonly code: "socket_path_too_long",
    readonly detail: string,
  ) {
    super(`${code}: ${detail}`);
  }
}

/**
 * Where Sauri keeps its internal state. Development uses `Sauri-dev` so it never touches the real installation.
 * `home` replaces the user's home folder for an isolated test run (SAURI_DESKTOP_HOME).
 */
export function appPaths(opts: { dev: boolean; home?: string }): AppPaths {
  const home = path.resolve(opts.home ?? os.homedir());
  const name = opts.dev ? "Sauri-dev" : "Sauri";
  const dataDir = path.join(home, "Library", "Application Support", name);
  return {
    dev: opts.dev,
    home,
    dataDir,
    configFile: path.join(dataDir, "config.json"),
    secretsDir: path.join(dataDir, "secrets"),
    runDir: path.join(dataDir, "run"),
    enginesDir: path.join(dataDir, "engines"),
    componentsDir: path.join(dataDir, "components"),
    updatesDir: path.join(dataDir, "updates"),
    cacheDir: path.join(dataDir, "cache"),
    electronDir: path.join(dataDir, "electron"),
    logsDir: path.join(home, "Library", "Logs", name),
  };
}

/** Default user folders: `~/Sauri/{Grabaciones,Base de datos,Modelos}` (`~/Sauri-dev/...` in development). */
export function defaultFolders(paths: Pick<AppPaths, "home" | "dev">): UserFolders {
  const root = path.join(paths.home, paths.dev ? "Sauri-dev" : "Sauri");
  return {
    recordings: path.join(root, "Grabaciones"),
    database: path.join(root, "Base de datos"),
    models: path.join(root, "Modelos"),
  };
}

export function pgDataDir(folders: UserFolders): string {
  return path.join(folders.database, "pgdata");
}

/** The PostgreSQL socket path; fails clearly when macOS cannot hold it. */
export function socketPath(runDir: string, port: number): string {
  const socket = path.join(runDir, `.s.PGSQL.${port}`);
  if (Buffer.byteLength(socket + SOCKET_LOCK_SUFFIX) > MAX_SOCKET_PATH_BYTES) {
    throw new PathError("socket_path_too_long", socket);
  }
  return socket;
}

export function ensurePrivateDir(dir: string): void {
  fs.mkdirSync(dir, { recursive: true, mode: 0o700 });
  fs.chmodSync(dir, 0o700);
}

export interface Marker {
  installId: string;
  kind: FolderKind;
}

export function readMarker(dir: string): Marker | null {
  try {
    const value = JSON.parse(fs.readFileSync(path.join(dir, MARKER_FILE), "utf8")) as Partial<Marker>;
    if (typeof value.installId !== "string" || !FOLDER_KINDS.includes(value.kind as FolderKind)) return null;
    return { installId: value.installId, kind: value.kind as FolderKind };
  } catch {
    return null;
  }
}

export function writeMarker(dir: string, marker: Marker): void {
  const file = path.join(dir, MARKER_FILE);
  const temporary = `${file}.tmp`;
  fs.writeFileSync(temporary, `${JSON.stringify(marker)}\n`, { mode: 0o644 });
  fs.renameSync(temporary, file);
}

export type FolderProblem = { kind: FolderKind; path: string; reason: "missing" | "marker_missing" | "foreign" };

/** Every user folder must exist and carry this installation's marker (Requirement 7.4). */
export function folderProblems(folders: UserFolders, installId: string): FolderProblem[] {
  const problems: FolderProblem[] = [];
  for (const kind of FOLDER_KINDS) {
    const dir = folders[kind];
    if (!fs.statSync(dir, { throwIfNoEntry: false })?.isDirectory()) {
      problems.push({ kind, path: dir, reason: "missing" });
      continue;
    }
    const marker = readMarker(dir);
    if (!marker) problems.push({ kind, path: dir, reason: "marker_missing" });
    else if (marker.installId !== installId || marker.kind !== kind) problems.push({ kind, path: dir, reason: "foreign" });
  }
  return problems;
}

export function expandHome(value: string, home: string): string {
  if (value === "~") return home;
  if (value.startsWith("~/")) return path.join(home, value.slice(2));
  return value;
}
