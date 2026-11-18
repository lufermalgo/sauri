// "Uninstall Sauri" (Requirement 10): stops the services, deletes Sauri's internal paths, and only on a separate,
// explicit answer moves the user's three folders to the Trash (kept by default). Nothing outside paths the app owns
// is ever touched: internal paths are fixed locations under ~/Library, user folders must carry this installation's
// `.sauri-folder` marker, a path that is itself a link is refused, and deletion never follows a link.
import fs from "node:fs";
import path from "node:path";
import { type AppPaths, FOLDER_KINDS, type FolderKind, readMarker, type UserFolders } from "./paths.ts";

export type FolderVerdict = "ok" | "missing" | "symlink" | "marker_missing" | "foreign" | "unsafe_location" | "symlink_escape";

export interface InternalTarget {
  path: string;
  bytes: number;
}

export interface FolderTarget {
  kind: FolderKind;
  path: string;
  bytes: number;
  verdict: FolderVerdict;
}

export interface AppBundleTarget {
  path: string;
  writable: boolean;
}

export interface UninstallPlan {
  internal: InternalTarget[];
  /** Internal paths that exist but are refused (a link in place of the folder). */
  refused: string[];
  folders: FolderTarget[];
  appBundle: AppBundleTarget | null;
}

export class UninstallError extends Error {
  constructor(
    readonly code: "symlink_refused" | "outside_library",
    readonly detail: string,
  ) {
    super(`${code}: ${detail}`);
  }
}

/**
 * Every internal path of the installation: data (config, secrets, run, engines, Electron profile), logs and, for the
 * installed app, what macOS keeps under the bundle id.
 */
export function internalPaths(paths: AppPaths, appId?: string): string[] {
  const library = path.join(paths.home, "Library");
  const list = [paths.dataDir, paths.logsDir];
  if (appId) {
    list.push(
      path.join(library, "Caches", appId),
      path.join(library, "HTTPStorages", appId),
      path.join(library, "Preferences", `${appId}.plist`),
      path.join(library, "Saved Application State", `${appId}.savedState`),
    );
  }
  return list;
}

function isInside(child: string, parent: string): boolean {
  const relative = path.relative(parent, child);
  return relative !== "" && !relative.startsWith("..") && !path.isAbsolute(relative);
}

/** Bytes of regular files under `target`, without following links. */
export function treeBytes(target: string): number {
  const info = fs.lstatSync(target, { throwIfNoEntry: false });
  if (!info) return 0;
  if (!info.isDirectory()) return info.isFile() ? info.size : 0;
  let total = 0;
  for (const entry of fs.readdirSync(target, { withFileTypes: true })) {
    const file = path.join(target, entry.name);
    if (entry.isDirectory()) total += treeBytes(file);
    else if (entry.isFile()) total += fs.lstatSync(file).size;
  }
  return total;
}

/** True when some link under `root` points outside it. */
export function hasEscapingLink(root: string): boolean {
  for (const entry of fs.readdirSync(root, { withFileTypes: true })) {
    const file = path.join(root, entry.name);
    if (entry.isSymbolicLink()) {
      const target = path.resolve(path.dirname(file), fs.readlinkSync(file));
      if (!isInside(target, root)) return true;
    } else if (entry.isDirectory() && hasEscapingLink(file)) return true;
  }
  return false;
}

/** May this user folder be moved to the Trash? Only a real folder with this installation's marker for its kind. */
export function checkUserFolder(kind: FolderKind, dir: string, installId: string, paths: AppPaths): FolderVerdict {
  const resolved = path.resolve(dir);
  const info = fs.lstatSync(resolved, { throwIfNoEntry: false });
  if (!info) return "missing";
  if (info.isSymbolicLink()) return "symlink";
  if (!info.isDirectory()) return "missing";
  // Never the root, the home folder, one of its ancestors, or anything holding Sauri's own internal folders.
  const protectedPaths = [paths.home, paths.dataDir, paths.logsDir];
  if (
    resolved === path.parse(resolved).root ||
    protectedPaths.some((item) => item === resolved || isInside(item, resolved))
  ) {
    return "unsafe_location";
  }
  const marker = readMarker(resolved);
  if (!marker) return "marker_missing";
  if (marker.installId !== installId || marker.kind !== kind) return "foreign";
  if (hasEscapingLink(resolved)) return "symlink_escape";
  return "ok";
}

/** The `.app` the process runs from (installed app only), and whether this user may move it. */
export function appBundleOf(execPath: string, packaged: boolean): AppBundleTarget | null {
  if (!packaged) return null;
  const bundle = path.resolve(execPath, "..", "..", "..");
  if (!bundle.endsWith(".app")) return null;
  let writable = true;
  try {
    fs.accessSync(bundle, fs.constants.W_OK);
    fs.accessSync(path.dirname(bundle), fs.constants.W_OK);
  } catch {
    // A read-only disk image, App Translocation or /Applications owned by another user.
    writable = false;
  }
  return { path: bundle, writable };
}

export function planUninstall(opts: {
  paths: AppPaths;
  folders?: UserFolders;
  installId: string;
  appId?: string;
  appBundle: AppBundleTarget | null;
}): UninstallPlan {
  const { paths } = opts;
  const library = path.join(paths.home, "Library");
  const internal: InternalTarget[] = [];
  const refused: string[] = [];
  for (const item of internalPaths(paths, opts.appId)) {
    if (!isInside(item, library)) throw new UninstallError("outside_library", item);
    const info = fs.lstatSync(item, { throwIfNoEntry: false });
    if (!info) continue;
    if (info.isSymbolicLink()) refused.push(item);
    else internal.push({ path: item, bytes: treeBytes(item) });
  }
  const folders: FolderTarget[] = opts.folders
    ? FOLDER_KINDS.map((kind) => {
        const dir = path.resolve((opts.folders as UserFolders)[kind]);
        const verdict = checkUserFolder(kind, dir, opts.installId, paths);
        return { kind, path: dir, verdict, bytes: verdict === "ok" ? treeBytes(dir) : 0 };
      })
    : [];
  return { internal, refused, folders, appBundle: opts.appBundle };
}

function removeContents(dir: string): void {
  try {
    fs.chmodSync(dir, 0o700);
  } catch {
    // Listing below reports the real problem.
  }
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const file = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      removeContents(file);
      fs.rmdirSync(file);
    } else {
      // Files, sockets and links alike: a link is removed, its target is never visited.
      fs.unlinkSync(file);
    }
  }
}

/** Deletes an internal path; refuses when the path itself is a link. */
export function removeOwnedTree(target: string): void {
  const info = fs.lstatSync(target, { throwIfNoEntry: false });
  if (!info) return;
  if (info.isSymbolicLink()) throw new UninstallError("symlink_refused", target);
  if (!info.isDirectory()) {
    fs.unlinkSync(target);
    return;
  }
  removeContents(target);
  fs.rmdirSync(target);
}

/**
 * A detached `/bin/sh` that waits for this process to end and removes the internal paths once more: the Electron
 * profile and logs can be written again while the app shuts down. The same link refusal applies (`[ -L ]`), and
 * `rm -R` never follows links inside the tree.
 */
export function afterExitSweep(pid: number, targets: string[]): { command: string; args: string[] } {
  const script = 'pid="$1"; shift; while kill -0 "$pid" 2>/dev/null; do sleep 0.2; done; for p in "$@"; do [ -L "$p" ] || rm -rf -- "$p"; done';
  return { command: "/bin/sh", args: ["-c", script, "sauri-uninstall", String(pid), ...targets] };
}

export interface UninstallChoice {
  proceed: boolean;
  removeApp: boolean;
}

export interface UninstallDeps {
  plan: () => UninstallPlan;
  /** Meetings being processed; null when the API does not answer. */
  processing: () => Promise<number | null>;
  confirm: (plan: UninstallPlan) => Promise<UninstallChoice>;
  confirmProcessing: (count: number) => Promise<boolean>;
  /** Asked separately; true only when the user explicitly picks "move to the Trash". */
  trashFolders: (folders: FolderTarget[]) => Promise<boolean>;
  stopServices: () => Promise<void>;
  trash: (target: string) => Promise<void>;
}

export interface UninstallReport {
  removed: string[];
  trashed: string[];
  kept: string[];
  failed: { path: string; error: string }[];
  appRemoved: boolean;
}

/** The whole flow; null when the user cancels at any question (nothing is touched then). */
export async function runUninstall(deps: UninstallDeps): Promise<UninstallReport | null> {
  const plan = deps.plan();
  const choice = await deps.confirm(plan);
  if (!choice.proceed) return null;
  const processing = await deps.processing();
  if (processing && processing > 0 && !(await deps.confirmProcessing(processing))) return null;
  const movable = plan.folders.filter((folder) => folder.verdict === "ok");
  const trashFolders = movable.length > 0 ? await deps.trashFolders(plan.folders) : false;

  await deps.stopServices();
  const report: UninstallReport = { removed: [], trashed: [], kept: [], failed: [], appRemoved: false };
  for (const target of plan.internal) {
    try {
      removeOwnedTree(target.path);
      report.removed.push(target.path);
    } catch (error) {
      report.failed.push({ path: target.path, error: error instanceof Error ? error.message : String(error) });
    }
  }
  for (const folder of plan.folders) {
    if (!trashFolders || folder.verdict !== "ok") {
      report.kept.push(folder.path);
      continue;
    }
    try {
      await deps.trash(folder.path);
      report.trashed.push(folder.path);
    } catch (error) {
      report.kept.push(folder.path);
      report.failed.push({ path: folder.path, error: error instanceof Error ? error.message : String(error) });
    }
  }
  if (choice.removeApp && plan.appBundle?.writable) {
    try {
      await deps.trash(plan.appBundle.path);
      report.appRemoved = true;
    } catch (error) {
      report.failed.push({ path: plan.appBundle.path, error: error instanceof Error ? error.message : String(error) });
    }
  }
  return report;
}
