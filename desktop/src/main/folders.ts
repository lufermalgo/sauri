// Checks a user folder before it is used (free space, write permission, another installation's marker) and
// prepares it: create, prove a real write, leave the `.sauri-folder` marker (Requirement 6.2–6.3).
import { randomBytes } from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import type { FolderInfo, FolderIssue } from "../shared/setup-api.ts";
import { freeBytes } from "./hardware.ts";
import { FOLDER_KINDS, type FolderKind, readMarker, type UserFolders, writeMarker } from "./paths.ts";

function nearestExisting(dir: string): string | null {
  let current = dir;
  while (!fs.existsSync(current)) {
    const parent = path.dirname(current);
    if (parent === current) return null;
    current = parent;
  }
  return current;
}

export function inspectFolder(kind: FolderKind, dir: string, installId: string): FolderInfo {
  const info: FolderInfo = { kind, path: dir, freeBytes: null };
  if (!path.isAbsolute(dir)) return { ...info, issue: "unavailable" };
  const existing = nearestExisting(dir);
  if (!existing) return { ...info, issue: "unavailable" };
  if (!fs.statSync(existing).isDirectory()) return { ...info, issue: "not_a_directory" };
  try {
    info.freeBytes = freeBytes(existing);
  } catch {
    return { ...info, issue: "unavailable" };
  }
  if (existing === dir) {
    const marker = readMarker(dir);
    if (marker && marker.installId !== installId) return { ...info, issue: "foreign" };
  }
  try {
    fs.accessSync(existing, fs.constants.W_OK);
  } catch {
    return { ...info, issue: "not_writable" };
  }
  return info;
}

/** All three folders, with `duplicate` when two kinds would share one folder. */
export function inspectFolders(folders: UserFolders, installId: string): FolderInfo[] {
  const resolved = FOLDER_KINDS.map((kind) => path.resolve(folders[kind]));
  return FOLDER_KINDS.map((kind, index) => {
    const info = inspectFolder(kind, folders[kind], installId);
    if (!info.issue && resolved.some((other, at) => at !== index && other === resolved[index])) {
      return { ...info, issue: "duplicate" as FolderIssue };
    }
    return info;
  });
}

function writeProbe(dir: string): void {
  const probe = path.join(dir, `.sauri-write-check-${randomBytes(6).toString("hex")}`);
  fs.writeFileSync(probe, "ok\n", { flag: "wx" });
  fs.rmSync(probe);
}

/** Creates the folders and marks them; returns the folders that could not be prepared (empty when all are ready). */
export function prepareFolders(folders: UserFolders, installId: string): FolderInfo[] {
  const checked = inspectFolders(folders, installId);
  if (checked.some((info) => info.issue)) return checked;
  const failed: FolderInfo[] = [];
  for (const info of checked) {
    try {
      fs.mkdirSync(info.path, { recursive: true });
      writeProbe(info.path);
      writeMarker(info.path, { installId, kind: info.kind });
    } catch {
      failed.push({ ...info, issue: "not_writable" });
    }
  }
  return failed.length > 0 ? checked.map((info) => failed.find((item) => item.kind === info.kind) ?? info) : [];
}
