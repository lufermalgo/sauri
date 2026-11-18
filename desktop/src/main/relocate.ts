// Moves one user folder (Requirement 7.2–7.3, design property 9): refuse while meetings are processed, check the
// new folder, stop the services, copy (resumable, through `.part` files), verify every file by relative path, size
// and SHA-256, and only then switch config.json. The old folder is never changed; deleting it is a separate choice.
import { createHash } from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import { pipeline } from "node:stream/promises";
import type { FolderUsage, RelocateResult } from "../shared/portal-api.ts";
import type { FolderIssue } from "../shared/setup-api.ts";
import type { AppConfig } from "./config.ts";
import { inspectFolder } from "./folders.ts";
import { freeBytes } from "./hardware.ts";
import { FOLDER_KINDS, type FolderKind, MARKER_FILE, readMarker, type UserFolders, writeMarker } from "./paths.ts";

/** Suffix of a file being copied; it never names a finished file, so an interrupted copy is easy to resume. */
export const PART_SUFFIX = ".sauri-relocate.part";
/** Room left on the new disk beyond the data itself. */
const SPACE_HEADROOM = 1.05;

export interface FileEntry {
  /** Path relative to the folder, with `/` separators. */
  relative: string;
  size: number;
}

export class RelocateError extends Error {
  constructor(
    readonly code: "unsupported_file" | "copy_failed" | "verify_failed",
    readonly detail = "",
  ) {
    super(detail ? `${code}: ${detail}` : code);
  }
}

/** Every regular file under `root` (the marker and our own `.part` files excluded), plus every directory. */
export function listTree(root: string): { files: FileEntry[]; dirs: string[] } {
  const files: FileEntry[] = [];
  const dirs: string[] = [];
  const walk = (relative: string) => {
    for (const entry of fs.readdirSync(path.join(root, relative), { withFileTypes: true })) {
      const child = relative ? `${relative}/${entry.name}` : entry.name;
      if (!relative && entry.name === MARKER_FILE) continue;
      if (entry.name.endsWith(PART_SUFFIX)) continue;
      if (entry.isDirectory()) {
        dirs.push(child);
        walk(child);
      } else if (entry.isFile()) {
        files.push({ relative: child, size: fs.statSync(path.join(root, child)).size });
      } else {
        // Links and special files could point outside the folder; moving them silently would not be a copy.
        throw new RelocateError("unsupported_file", child);
      }
    }
  };
  walk("");
  files.sort((a, b) => a.relative.localeCompare(b.relative));
  return { files, dirs };
}

export function folderSize(root: string): number {
  let total = 0;
  const walk = (dir: string) => {
    for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
      const child = path.join(dir, entry.name);
      if (entry.isDirectory()) walk(child);
      else if (entry.isFile()) total += fs.statSync(child).size;
    }
  };
  walk(root);
  return total;
}

export async function sha256(file: string): Promise<string> {
  const hash = createHash("sha256");
  await pipeline(fs.createReadStream(file), hash);
  return hash.digest("hex");
}

function sameSize(file: string, size: number): boolean {
  return fs.statSync(file, { throwIfNoEntry: false })?.size === size;
}

/** Permission bits of the source: PostgreSQL refuses a data folder that others can read. */
function modeOf(file: string): number {
  return fs.statSync(file).mode & 0o7777;
}

/** Copies through `<name>.sauri-relocate.part`, fsync and rename: a finished name always holds a whole file. */
async function copyFile(source: string, target: string): Promise<void> {
  const part = `${target}${PART_SUFFIX}`;
  await pipeline(fs.createReadStream(source), fs.createWriteStream(part));
  fs.chmodSync(part, modeOf(source));
  const fd = fs.openSync(part, "r");
  try {
    fs.fsyncSync(fd);
  } finally {
    fs.closeSync(fd);
  }
  fs.renameSync(part, target);
}

export interface CopyHooks {
  /** Called before each file is copied; tests use it to interrupt a copy. */
  beforeFile?: (entry: FileEntry) => void;
}

/** Bytes still to copy: files already at the target with the same size are resumed, not copied again. */
export function bytesToCopy(source: string, target: string): number {
  const { files } = listTree(source);
  return files.reduce((total, entry) => total + (sameSize(path.join(target, entry.relative), entry.size) ? 0 : entry.size), 0);
}

/**
 * Copies `source` into `target` and checks property 9: every source file exists at the target with the same
 * relative path, size and SHA-256. Files already copied by an interrupted run are kept when they match.
 */
export async function copyAndVerify(source: string, target: string, hooks: CopyHooks = {}): Promise<FileEntry[]> {
  const { files, dirs } = listTree(source);
  fs.mkdirSync(target, { recursive: true });
  for (const dir of dirs) fs.mkdirSync(path.join(target, dir), { recursive: true });
  const digests = new Map<string, string>();
  for (const entry of files) {
    hooks.beforeFile?.(entry);
    const from = path.join(source, entry.relative);
    const to = path.join(target, entry.relative);
    const digest = await sha256(from);
    digests.set(entry.relative, digest);
    if (sameSize(to, entry.size) && (await sha256(to)) === digest) continue;
    try {
      await copyFile(from, to);
    } catch (error) {
      throw new RelocateError("copy_failed", `${entry.relative}: ${error instanceof Error ? error.message : String(error)}`);
    }
  }
  // Folder permissions last, so a read-only source folder never blocks copying into it.
  for (const dir of dirs) fs.chmodSync(path.join(target, dir), modeOf(path.join(source, dir)));
  for (const entry of files) {
    const to = path.join(target, entry.relative);
    if (!sameSize(to, entry.size) || (await sha256(to)) !== digests.get(entry.relative)) {
      throw new RelocateError("verify_failed", entry.relative);
    }
  }
  return files;
}

export type TargetIssue = FolderIssue | "same" | "nested" | "not_empty" | "no_space";

function inside(child: string, parent: string): boolean {
  const relative = path.relative(parent, child);
  return relative === "" || (!relative.startsWith("..") && !path.isAbsolute(relative));
}

/** Folders that are not ours and not empty are refused, so a move never mixes Sauri data with other files. */
function foreignContent(dir: string, installId: string, kind: FolderKind): boolean {
  if (!fs.existsSync(dir)) return false;
  const marker = readMarker(dir);
  if (marker && marker.installId === installId && marker.kind === kind) return false;
  return fs.readdirSync(dir).some((name) => name !== ".DS_Store");
}

/** Why `target` cannot receive the `kind` folder, or null when it can. */
export function checkTarget(
  kind: FolderKind,
  folders: UserFolders,
  target: string,
  installId: string,
): { issue: TargetIssue; neededBytes?: number; freeBytes?: number } | null {
  const source = path.resolve(folders[kind]);
  const resolved = path.resolve(target);
  if (resolved === source) return { issue: "same" };
  if (inside(resolved, source) || inside(source, resolved)) return { issue: "nested" };
  if (FOLDER_KINDS.some((other) => other !== kind && inside(resolved, path.resolve(folders[other])))) {
    return { issue: "duplicate" };
  }
  const info = inspectFolder(kind, resolved, installId);
  if (info.issue) return { issue: info.issue };
  if (foreignContent(resolved, installId, kind)) return { issue: "not_empty" };
  const needed = Math.ceil(bytesToCopy(source, resolved) * SPACE_HEADROOM);
  const free = info.freeBytes ?? 0;
  if (needed > free) return { issue: "no_space", neededBytes: needed, freeBytes: free };
  return null;
}

export interface RelocateDeps {
  config: () => AppConfig;
  update: (change: Partial<AppConfig>) => AppConfig;
  /** Meetings in flight, or null when the API does not answer. */
  processing: () => Promise<number | null>;
  chooseFolder: (kind: FolderKind) => Promise<string | null>;
  /** Asked only after the new folder is in use: first an offer, then a confirmation. */
  confirmTrash: (kind: FolderKind, previous: string) => Promise<boolean>;
  trash: (dir: string) => Promise<void>;
  stopServices: () => Promise<void>;
  /** Starts the services on the folders config.json holds at that moment. */
  startServices: () => Promise<void>;
  log: (line: string) => void;
  hooks?: CopyHooks;
}

/** The whole flow of «Cambiar». Services are restarted on the old folder when anything fails after they stop. */
export async function relocate(kind: FolderKind, deps: RelocateDeps): Promise<RelocateResult> {
  const count = await deps.processing();
  if (count === null) return { ok: false, reason: "status_unavailable" };
  if (count > 0) return { ok: false, reason: "processing", count };
  const chosen = await deps.chooseFolder(kind);
  if (!chosen) return { ok: false, reason: "cancelled" };
  const config = deps.config();
  if (!config.paths) return { ok: false, reason: "unavailable" };
  const folders = config.paths;
  const target = path.resolve(chosen);
  let problem: ReturnType<typeof checkTarget>;
  try {
    problem = checkTarget(kind, folders, target, config.installId);
  } catch (error) {
    if (error instanceof RelocateError) return { ok: false, reason: error.code, detail: error.detail };
    throw error;
  }
  if (problem) return { ok: false, reason: problem.issue, neededBytes: problem.neededBytes, freeBytes: problem.freeBytes };
  // A job may have started while the dialog was open.
  const again = await deps.processing();
  if (again === null) return { ok: false, reason: "status_unavailable" };
  if (again > 0) return { ok: false, reason: "processing", count: again };

  const previous = folders[kind];
  deps.log(`relocate ${kind}: ${previous} -> ${target}`);
  await deps.stopServices();
  try {
    fs.mkdirSync(target, { recursive: true });
    // Marked first: a retry after an interruption recognizes the half-copied folder as ours and resumes.
    writeMarker(target, { installId: config.installId, kind });
    const files = await copyAndVerify(previous, target, deps.hooks);
    deps.update({ paths: { ...folders, [kind]: target } });
    deps.log(`relocate ${kind}: ${files.length} files copied and verified`);
  } catch (error) {
    const code = error instanceof RelocateError ? error.code : "copy_failed";
    const detail = error instanceof RelocateError ? error.detail : error instanceof Error ? error.message : String(error);
    deps.log(`relocate ${kind} failed (${code}): ${detail}`);
    await deps.startServices();
    return { ok: false, reason: code, detail };
  }
  await deps.startServices();
  let previousTrashed = false;
  if (await deps.confirmTrash(kind, previous)) {
    await deps.trash(previous);
    previousTrashed = true;
    deps.log(`relocate ${kind}: previous folder moved to the Trash`);
  }
  return { ok: true, kind, path: target, previous, previousTrashed };
}

/** What the storage page shows: each folder, the space it takes and the free space of its disk. */
export function folderUsage(folders: UserFolders): FolderUsage[] {
  return FOLDER_KINDS.map((kind) => {
    const dir = folders[kind];
    const present = fs.statSync(dir, { throwIfNoEntry: false })?.isDirectory() === true;
    return {
      kind,
      path: dir,
      usedBytes: present ? folderSize(dir) : null,
      freeBytes: present ? freeBytes(dir) : null,
    };
  });
}
