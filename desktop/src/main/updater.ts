// Updates (design D12, Requirement 9), the APX pattern with one difference: the database is migrated by the NEW
// version's core before the app is replaced, from a copy of the stopped `pgdata`, so a failed migration leaves the
// data and the app exactly as they were (Property 10).
//
//   check  → the release feed (GitHub Releases of the download place) names a newer x.y.z with its zip and .sha256
//   stage  → the zip is downloaded (resumable .part, size-capped, only allowed hosts), checked against its .sha256,
//            unpacked with ditto into updates/<version>/ and its Info.plist version confirmed
//   apply  → only with nothing processing: stop the services, copy pgdata to <database>/backups/pgdata-<from>
//            (only the last copy is kept), run `alembic upgrade head` with the staged core, then swap Sauri.app and
//            relaunch; on any failure restore pgdata from the copy, keep the old app and say why
//
// Only HTTP requests leave the Mac (the feed and the files); they carry no user data, cookie or token.
import { spawn } from "node:child_process";
import { createHash } from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import { allowedUrl, type ReleaseSource } from "./releases.ts";

export const CHECK_EVERY_MS = 6 * 3600_000;
/** The first automatic check waits for the services to settle. */
export const FIRST_CHECK_DELAY_MS = 90_000;
const MAX_REDIRECTS = 5;
const FEED_MAX_BYTES = 2 << 20;
const USER_AGENT = "Sauri-Desktop";
const STAGED_FILE = "staged.json";

export const zipName = (version: string) => `Sauri-${version}-mac-arm64.zip`;

export class UpdateError extends Error {
  constructor(
    readonly code: string,
    readonly detail = "",
  ) {
    super(detail ? `${code}: ${detail}` : code);
  }
}

const SEMVER = /^v?(\d{1,4})\.(\d{1,4})\.(\d{1,6})$/;

/** Plain x.y.z (a leading v is allowed); negative when a is older than b, 0 when equal; null when not x.y.z. */
export function compareVersions(a: string, b: string): number | null {
  const pa = SEMVER.exec(a);
  const pb = SEMVER.exec(b);
  if (!pa || !pb) return null;
  for (let i = 1; i <= 3; i += 1) {
    const difference = Number(pa[i]) - Number(pb[i]);
    if (difference) return difference;
  }
  return 0;
}

export interface ReleaseAsset {
  name: string;
  url: string;
  size: number;
}

export interface Release {
  version: string;
  zip: ReleaseAsset;
  sha256: ReleaseAsset;
}

interface FeedAsset {
  name?: unknown;
  size?: unknown;
  browser_download_url?: unknown;
}

function assetOf(raw: FeedAsset[], name: string): ReleaseAsset | null {
  const found = raw.find((item) => item?.name === name);
  if (!found || typeof found.browser_download_url !== "string" || typeof found.size !== "number") return null;
  if (!Number.isSafeInteger(found.size) || found.size <= 0) return null;
  return { name, url: found.browser_download_url, size: found.size };
}

/**
 * The newest published release above `current` that carries this Mac's zip and its .sha256, or null. Drafts,
 * pre-releases, tags that are not x.y.z (the components' `diar-…` tags) and releases without the files are skipped.
 */
export function pickRelease(feed: unknown, current: string): Release | null {
  const list = Array.isArray(feed) ? feed : feed && typeof feed === "object" ? [feed] : [];
  let best: Release | null = null;
  for (const item of list as Record<string, unknown>[]) {
    if (!item || item.draft === true || item.prerelease === true || typeof item.tag_name !== "string") continue;
    const version = item.tag_name.replace(/^v/, "");
    const newer = compareVersions(version, current);
    if (newer === null || newer <= 0) continue;
    const assets = Array.isArray(item.assets) ? (item.assets as FeedAsset[]) : [];
    const zip = assetOf(assets, zipName(version));
    const sha256 = assetOf(assets, `${zipName(version)}.sha256`);
    if (!zip || !sha256) continue;
    if (!best || (compareVersions(version, best.version) ?? 0) > 0) best = { version, zip, sha256 };
  }
  return best;
}

/** The hex digest a `.sha256` file gives for `name` (`<hex>  <name>`, as `shasum -a 256` writes it). */
export function parseSha256File(text: string, name: string): string | null {
  for (const line of text.split("\n")) {
    const match = /^([0-9a-f]{64})\s+\*?(.+)$/.exec(line.trim());
    if (match && match[2] === name) return match[1];
  }
  return null;
}

export type Fetch = (url: string, init: RequestInit) => Promise<Response>;

/** One GET whose every redirect hop must stay on the allow-list; nothing but the request itself is sent. */
export async function fetchAllowed(
  source: ReleaseSource,
  url: string,
  headers: Record<string, string>,
  fetchImpl: Fetch = fetch,
): Promise<Response> {
  let target = url;
  for (let hop = 0; hop <= MAX_REDIRECTS; hop += 1) {
    if (!allowedUrl(source, target)) throw new UpdateError(hop === 0 ? "url_not_allowed" : "redirect_not_allowed");
    const response = await fetchImpl(target, {
      headers: { "User-Agent": USER_AGENT, ...headers },
      redirect: "manual",
      credentials: "omit",
      signal: AbortSignal.timeout(30 * 60_000),
    });
    if ([301, 302, 303, 307, 308].includes(response.status)) {
      const location = response.headers.get("location");
      await response.body?.cancel();
      if (!location) throw new UpdateError("redirect_not_allowed");
      target = new URL(location, target).href;
      continue;
    }
    return response;
  }
  throw new UpdateError("too_many_redirects");
}

/** The feed, read with a size cap. */
export async function fetchFeed(source: ReleaseSource, fetchImpl: Fetch = fetch): Promise<unknown> {
  const response = await fetchAllowed(source, source.feedUrl, { Accept: "application/vnd.github+json" }, fetchImpl);
  if (response.status !== 200) throw new UpdateError("feed_http_error", String(response.status));
  const text = await response.text();
  if (text.length > FEED_MAX_BYTES) throw new UpdateError("feed_too_large");
  try {
    return JSON.parse(text) as unknown;
  } catch {
    throw new UpdateError("feed_invalid");
  }
}

/**
 * Downloads `asset` into `file` through `<file>.part`, resuming with Range, never past the size the feed gave.
 * `file` appears only when every byte arrived; the caller checks the hash.
 */
export async function downloadAsset(
  source: ReleaseSource,
  asset: ReleaseAsset,
  file: string,
  fetchImpl: Fetch = fetch,
  onProgress: (done: number, total: number) => void = () => undefined,
): Promise<void> {
  const part = `${file}.part`;
  let done = fs.statSync(part, { throwIfNoEntry: false })?.size ?? 0;
  if (done > asset.size) {
    fs.rmSync(part, { force: true });
    done = 0;
  }
  const headers: Record<string, string> = { Accept: "application/octet-stream", "Accept-Encoding": "identity" };
  if (done > 0) headers.Range = `bytes=${done}-`;
  const response = await fetchAllowed(source, asset.url, headers, fetchImpl);
  if (response.status === 206) {
    const range = /^bytes (\d+)-(\d+)\/(\d+)$/.exec(response.headers.get("content-range") ?? "");
    if (!range || Number(range[1]) !== done || Number(range[3]) !== asset.size) throw new UpdateError("bad_range");
  } else if (response.status === 200) {
    done = 0; // the server ignored Range: start over
  } else {
    await response.body?.cancel();
    throw new UpdateError("download_http_error", String(response.status));
  }
  if (!response.body) throw new UpdateError("download_failed");
  // A plain read loop: every chunk is counted against the size the feed gave before it is written.
  const reader = response.body.getReader();
  const out = await fs.promises.open(part, done > 0 ? "a" : "w", 0o600);
  let received = done;
  try {
    for (;;) {
      const { value, done: finished } = await reader.read();
      if (finished) break;
      received += value.byteLength;
      if (received > asset.size) throw new UpdateError("size_exceeded");
      await out.write(value);
      onProgress(received, asset.size);
    }
    await out.sync();
  } catch (error) {
    await reader.cancel().catch(() => undefined);
    throw error;
  } finally {
    await out.close();
  }
  if (received !== asset.size) throw new UpdateError("size_mismatch");
  fs.renameSync(part, file);
}

export function sha256File(file: string): Promise<string> {
  return new Promise((resolve, reject) => {
    const hash = createHash("sha256");
    fs.createReadStream(file)
      .on("data", (chunk) => hash.update(chunk))
      .on("error", reject)
      .on("end", () => resolve(hash.digest("hex")));
  });
}

export function run(command: string, args: string[]): Promise<{ code: number | null; stdout: string }> {
  return new Promise((resolve) => {
    const child = spawn(command, args, { stdio: ["ignore", "pipe", "ignore"] });
    const out: Buffer[] = [];
    child.stdout.on("data", (chunk: Buffer) => out.push(chunk));
    child.once("error", () => resolve({ code: null, stdout: "" }));
    child.once("close", (code) => resolve({ code, stdout: Buffer.concat(out).toString("utf8") }));
  });
}

export interface Staged {
  version: string;
  /** The unpacked Sauri.app, ready to be moved into place. */
  appPath: string;
  /** The verified zip, kept for a manual install when the app's folder is not writable. */
  zipPath: string;
  sha256: string;
}

export function stagedFile(updatesDir: string): string {
  return path.join(updatesDir, STAGED_FILE);
}

/** The staged version still on disk, or null. */
export function readStaged(updatesDir: string): Staged | null {
  try {
    const value = JSON.parse(fs.readFileSync(stagedFile(updatesDir), "utf8")) as Staged;
    if (typeof value.version !== "string" || typeof value.appPath !== "string") return null;
    if (!fs.existsSync(path.join(value.appPath, "Contents", "Info.plist"))) return null;
    return value;
  } catch {
    return null;
  }
}

/** The version an app bundle declares (CFBundleShortVersionString). */
export async function bundleVersion(appPath: string): Promise<string | null> {
  const plist = path.join(appPath, "Contents", "Info.plist");
  const result = await run("/usr/bin/plutil", ["-extract", "CFBundleShortVersionString", "raw", "-o", "-", plist]);
  return result.code === 0 ? result.stdout.trim() : null;
}

/** Downloads, checks and unpacks `release` under `updatesDir`; any failure leaves nothing behind. */
export async function stageRelease(
  source: ReleaseSource,
  release: Release,
  updatesDir: string,
  fetchImpl: Fetch = fetch,
  onProgress?: (done: number, total: number) => void,
): Promise<Staged> {
  const existing = readStaged(updatesDir);
  if (existing?.version === release.version) return existing;
  const dir = path.join(updatesDir, release.version);
  fs.mkdirSync(dir, { recursive: true, mode: 0o700 });
  const zipPath = path.join(dir, release.zip.name);
  const unpacked = path.join(dir, "app");
  try {
    if (release.sha256.size > 4096) throw new UpdateError("sha256_file_too_large");
    const sumFile = path.join(dir, release.sha256.name);
    fs.rmSync(sumFile, { force: true });
    await downloadAsset(source, release.sha256, sumFile, fetchImpl);
    const expected = parseSha256File(fs.readFileSync(sumFile, "utf8"), release.zip.name);
    if (!expected) throw new UpdateError("sha256_file_invalid");
    if (!fs.existsSync(zipPath)) await downloadAsset(source, release.zip, zipPath, fetchImpl, onProgress);
    const actual = await sha256File(zipPath);
    if (actual !== expected) {
      fs.rmSync(zipPath, { force: true });
      throw new UpdateError("sha256_mismatch");
    }
    fs.rmSync(unpacked, { recursive: true, force: true });
    fs.mkdirSync(unpacked, { mode: 0o700 });
    // ditto keeps the bundle's links, modes and signature, as Finder does.
    if ((await run("/usr/bin/ditto", ["-x", "-k", zipPath, unpacked])).code !== 0) throw new UpdateError("unzip_failed");
    const appPath = path.join(unpacked, "Sauri.app");
    if ((await bundleVersion(appPath)) !== release.version) throw new UpdateError("staged_version_mismatch");
    const staged: Staged = { version: release.version, appPath, zipPath, sha256: actual };
    // An older staged version goes away: only one waits at a time.
    for (const entry of fs.readdirSync(updatesDir)) {
      if (entry !== release.version && entry !== STAGED_FILE) fs.rmSync(path.join(updatesDir, entry), { recursive: true, force: true });
    }
    const temporary = `${stagedFile(updatesDir)}.tmp`;
    fs.writeFileSync(temporary, `${JSON.stringify(staged, null, 2)}\n`, { mode: 0o600 });
    fs.renameSync(temporary, stagedFile(updatesDir));
    return staged;
  } catch (error) {
    fs.rmSync(unpacked, { recursive: true, force: true });
    if (error instanceof UpdateError && error.code !== "download_http_error" && error.code !== "download_failed") {
      fs.rmSync(`${zipPath}.part`, { force: true });
    }
    throw error;
  }
}

// --- apply -----------------------------------------------------------------------------------------------------

/** Copy-on-write clone where the disk allows it; modes and times kept, links kept as links. */
function cloneTree(from: string, to: string): void {
  fs.cpSync(from, to, {
    recursive: true,
    mode: fs.constants.COPYFILE_FICLONE,
    verbatimSymlinks: true,
    preserveTimestamps: true,
    errorOnExist: true,
    force: false,
  });
}

export function backupDir(databaseDir: string, fromVersion: string): string {
  return path.join(databaseDir, "backups", `pgdata-${fromVersion}`);
}

/** Copies the stopped pgdata to backups/pgdata-<from>; earlier copies are removed only once the new one is whole. */
export function backupPgdata(databaseDir: string, fromVersion: string): string {
  const pgdata = path.join(databaseDir, "pgdata");
  const backups = path.join(databaseDir, "backups");
  const target = backupDir(databaseDir, fromVersion);
  const partial = path.join(backups, `.pgdata-${fromVersion}.part`);
  fs.mkdirSync(backups, { recursive: true, mode: 0o700 });
  fs.rmSync(partial, { recursive: true, force: true });
  cloneTree(pgdata, partial);
  fs.rmSync(target, { recursive: true, force: true });
  fs.renameSync(partial, target);
  for (const entry of fs.readdirSync(backups)) {
    if (entry.startsWith("pgdata-") && path.join(backups, entry) !== target) {
      fs.rmSync(path.join(backups, entry), { recursive: true, force: true });
    }
  }
  return target;
}

/** Puts pgdata back exactly as the copy is (the copy stays, as the last backup). */
export function restorePgdata(databaseDir: string, backup: string): void {
  const pgdata = path.join(databaseDir, "pgdata");
  const incoming = path.join(databaseDir, ".pgdata.restore");
  fs.rmSync(incoming, { recursive: true, force: true });
  cloneTree(backup, incoming);
  fs.rmSync(pgdata, { recursive: true, force: true });
  fs.renameSync(incoming, pgdata);
}

/** Moves a bundle; across disks (EXDEV) it is copied with ditto and the source removed. */
async function moveBundle(from: string, to: string): Promise<void> {
  try {
    fs.renameSync(from, to);
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code !== "EXDEV") throw error;
    if ((await run("/usr/bin/ditto", [from, to])).code !== 0) {
      fs.rmSync(to, { recursive: true, force: true });
      throw new UpdateError("copy_failed");
    }
    fs.rmSync(from, { recursive: true, force: true });
  }
}

/** Swaps the running bundle for the staged one; the old one comes back if the new one cannot go in. */
export async function swapBundle(current: string, staged: string): Promise<void> {
  const previous = path.join(path.dirname(current), `.${path.basename(current, ".app")}-previous.app`);
  fs.rmSync(previous, { recursive: true, force: true });
  fs.renameSync(current, previous);
  try {
    await moveBundle(staged, current);
  } catch (error) {
    fs.rmSync(current, { recursive: true, force: true });
    fs.renameSync(previous, current);
    throw error;
  }
  fs.rmSync(previous, { recursive: true, force: true });
}

export interface AppBundleInfo {
  path: string;
  writable: boolean;
}

export type ApplyFailure =
  | "processing"
  | "status_unavailable"
  | "not_writable"
  | "backup_failed"
  | "migration_failed"
  | "swap_failed";

export type ApplyResult = { ok: true; version: string } | { ok: false; reason: ApplyFailure; count?: number; detail?: string };

export interface ApplyDeps {
  /** Meetings being processed now; null when the API does not answer. */
  processing(): Promise<number | null>;
  stopServices(): Promise<void>;
  /** PostgreSQL alone (the current runtime's), for the migration. */
  startDatabase(): Promise<void>;
  stopDatabase(): Promise<void>;
  /** `alembic upgrade head` with the staged app's core against the data; false when it fails. */
  migrate(stagedApp: string): Promise<boolean>;
  /** The services of the current app again, after a failure. */
  restartServices(): Promise<void>;
  swap(current: string, staged: string): Promise<void>;
  /** Saves that the data now belongs to `version`. */
  applied(version: string): void;
  relaunch(): void;
  log(line: string): void;
}

/** Applies a staged version; see the header. Never touches anything while a meeting is being processed. */
export async function applyUpdate(opts: {
  staged: Staged;
  bundle: AppBundleInfo | null;
  databaseDir: string;
  fromVersion: string;
  deps: ApplyDeps;
}): Promise<ApplyResult> {
  const { staged, bundle, databaseDir, fromVersion, deps } = opts;
  // Without a writable app the swap could not happen: nothing is migrated, the person installs it by hand.
  if (!bundle?.writable) return { ok: false, reason: "not_writable", detail: staged.zipPath };
  const count = await deps.processing();
  if (count === null) return { ok: false, reason: "status_unavailable" };
  if (count > 0) return { ok: false, reason: "processing", count };
  deps.log(`update ${fromVersion} -> ${staged.version}: stopping services`);
  await deps.stopServices();
  let backup: string;
  try {
    backup = backupPgdata(databaseDir, fromVersion);
  } catch (error) {
    deps.log(`update: backup failed (${error instanceof Error ? error.message : String(error)})`);
    await deps.restartServices();
    return { ok: false, reason: "backup_failed" };
  }
  deps.log(`update: pgdata copied to ${backup}`);
  let migrated = false;
  try {
    await deps.startDatabase();
    migrated = await deps.migrate(staged.appPath);
  } catch (error) {
    deps.log(`update: migration could not run (${error instanceof Error ? error.message : String(error)})`);
  } finally {
    await deps.stopDatabase().catch(() => undefined);
  }
  if (!migrated) {
    restorePgdata(databaseDir, backup);
    deps.log("update: migration failed, pgdata restored from the copy, the current app stays");
    await deps.restartServices();
    return { ok: false, reason: "migration_failed" };
  }
  try {
    await deps.swap(bundle.path, staged.appPath);
  } catch (error) {
    restorePgdata(databaseDir, backup);
    deps.log(`update: the app could not be replaced (${error instanceof Error ? error.message : String(error)})`);
    await deps.restartServices();
    return { ok: false, reason: "swap_failed" };
  }
  deps.applied(staged.version);
  deps.log(`update: ${staged.version} in place, relaunching`);
  deps.relaunch();
  return { ok: true, version: staged.version };
}

// --- startup ---------------------------------------------------------------------------------------------------

export type StartupMigration =
  | { ok: true; backup: string | null }
  | { ok: false; reason: "backup_failed" | "migration_failed"; restored: boolean };

/**
 * Requirement 9.3 on every start, whatever brought the new version (the updater, a manual install, a downgrade):
 * when the data was last used by another app version (or by an unknown one), the stopped pgdata is copied to
 * backups/pgdata-<data version> first (only the last copy is kept), then the migrations run. A failure restores
 * the copy and leaves the database stopped, so nothing starts on half-migrated data. The caller saves the new
 * data version only after `ok`.
 */
export async function migrateOnStart(opts: {
  databaseDir: string;
  /** `config.appVersionOfData`; undefined for data from before it was recorded. */
  dataVersion: string | undefined;
  appVersion: string;
  /** The database is running (setup phase A started it); it is stopped before a copy. */
  databaseRunning: boolean;
  startDatabase(): Promise<void>;
  stopDatabase(): Promise<void>;
  /** Creates the database if needed and runs `alembic upgrade head`; false when it fails. */
  migrate(): Promise<boolean>;
  log(line: string): void;
}): Promise<StartupMigration> {
  const pgdata = path.join(opts.databaseDir, "pgdata");
  const hasData = fs.existsSync(path.join(pgdata, "PG_VERSION"));
  let backup: string | null = null;
  if (hasData && opts.dataVersion !== opts.appVersion) {
    const from = opts.dataVersion ?? "unknown";
    if (opts.databaseRunning) await opts.stopDatabase();
    try {
      backup = backupPgdata(opts.databaseDir, from);
    } catch (error) {
      opts.log(`startup: database copy failed (${error instanceof Error ? error.message : String(error)})`);
      return { ok: false, reason: "backup_failed", restored: false };
    }
    opts.log(`startup: data of ${from} copied to ${backup} before migrating to ${opts.appVersion}`);
  }
  let migrated = false;
  try {
    await opts.startDatabase();
    migrated = await opts.migrate();
  } catch (error) {
    opts.log(`startup: migration could not run (${error instanceof Error ? error.message : String(error)})`);
  }
  if (migrated) return { ok: true, backup };
  await opts.stopDatabase().catch(() => undefined);
  if (backup) {
    restorePgdata(opts.databaseDir, backup);
    opts.log("startup: migration failed, pgdata restored from the copy; services not started");
  }
  return { ok: false, reason: "migration_failed", restored: backup !== null };
}
