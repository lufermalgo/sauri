import { execFileSync } from "node:child_process";
import { createHash } from "node:crypto";
import fs from "node:fs";
import http from "node:http";
import type { AddressInfo } from "node:net";
import os from "node:os";
import path from "node:path";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { appPaths, defaultFolders } from "./paths.ts";
import { portPlan } from "./ports.ts";
import { allowedUrl, type ReleaseSource, releaseSource, releasesRepo } from "./releases.ts";
import { bundleLayout, ensureSecrets, prepareDatabase, type ServiceContext } from "./services.ts";
import { RotatingLog } from "./supervisor.ts";
import {
  type ApplyDeps,
  applyUpdate,
  backupDir,
  compareVersions,
  migrateOnStart,
  parseSha256File,
  pickRelease,
  readStaged,
  type Release,
  type Staged,
  stageRelease,
  swapBundle,
  UpdateError,
  zipName,
} from "./updater.ts";

const REPO = "owner/sauri-app";
let dir: string;

beforeEach(() => {
  dir = fs.mkdtempSync(path.join(os.tmpdir(), "sauri-updater-"));
});
afterEach(() => fs.rmSync(dir, { recursive: true, force: true }));

/** Every file's relative path, mode and SHA-256: two trees are identical when this is. */
function treeDigest(root: string): string {
  const lines: string[] = [];
  (function walk(current: string) {
    for (const entry of fs.readdirSync(current, { withFileTypes: true }).sort((a, b) => a.name.localeCompare(b.name))) {
      const full = path.join(current, entry.name);
      const rel = path.relative(root, full);
      const info = fs.lstatSync(full);
      if (entry.isDirectory()) {
        lines.push(`d ${rel} ${info.mode & 0o777}`);
        walk(full);
      } else if (entry.isSymbolicLink()) lines.push(`l ${rel} ${fs.readlinkSync(full)}`);
      else lines.push(`f ${rel} ${info.mode & 0o777} ${createHash("sha256").update(fs.readFileSync(full)).digest("hex")}`);
    }
  })(root);
  return createHash("sha256").update(lines.join("\n")).digest("hex");
}

/** A minimal Sauri.app: Info.plist with its version, an executable and its resources. */
function fakeApp(at: string, version: string): string {
  const app = path.join(at, "Sauri.app");
  fs.mkdirSync(path.join(app, "Contents", "MacOS"), { recursive: true });
  fs.mkdirSync(path.join(app, "Contents", "Resources", "app-sources", "backend"), { recursive: true });
  fs.writeFileSync(
    path.join(app, "Contents", "Info.plist"),
    `<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n` +
      `<plist version="1.0"><dict><key>CFBundleShortVersionString</key><string>${version}</string></dict></plist>\n`,
  );
  fs.writeFileSync(path.join(app, "Contents", "MacOS", "Sauri"), `#!/bin/sh\necho ${version}\n`, { mode: 0o755 });
  fs.writeFileSync(path.join(app, "Contents", "Resources", "build.json"), JSON.stringify({ version }));
  return app;
}

describe("versions and the feed", () => {
  it("compares plain x.y.z", () => {
    expect(compareVersions("0.1.1", "0.1.0")).toBeGreaterThan(0);
    expect(compareVersions("0.1.0", "0.1.0")).toBe(0);
    expect(compareVersions("v0.2.0", "0.10.0")).toBeLessThan(0);
    expect(compareVersions("1.0.0", "0.99.99")).toBeGreaterThan(0);
    expect(compareVersions("0.1.0-beta", "0.1.0")).toBeNull();
    expect(compareVersions("diar-0.1.0", "0.1.0")).toBeNull();
  });

  const asset = (name: string, size = 10) => ({ name, size, browser_download_url: `https://github.com/${REPO}/releases/download/x/${name}` });
  const release = (tag: string, extra: Record<string, unknown> = {}, names?: string[]) => {
    const version = tag.replace(/^v/, "");
    return {
      tag_name: tag,
      draft: false,
      prerelease: false,
      assets: (names ?? [zipName(version), `${zipName(version)}.sha256`]).map((name) => asset(name)),
      ...extra,
    };
  };

  it("picks the newest published release that carries this Mac's zip and its .sha256", () => {
    const feed = [
      release("v0.3.0", { draft: true }),
      release("v0.2.5", { prerelease: true }),
      release("diar-0.9.0", {}, ["diar-0.9.0-mac-arm64.tar.gz"]),
      release("v0.2.2", {}, [zipName("0.2.2")]),
      release("v0.1.9"),
      release("v0.2.0"),
      release("v0.0.9"),
    ];
    const found = pickRelease(feed, "0.1.0");
    expect(found?.version).toBe("0.2.0");
    expect(found?.zip.name).toBe("Sauri-0.2.0-mac-arm64.zip");
    expect(found?.sha256.name).toBe("Sauri-0.2.0-mac-arm64.zip.sha256");
    expect(pickRelease(feed, "0.2.0")).toBeNull();
    expect(pickRelease(release("v0.1.1"), "0.1.0")?.version).toBe("0.1.1");
    expect(pickRelease({ message: "Not Found" }, "0.1.0")).toBeNull();
    expect(pickRelease("garbage", "0.1.0")).toBeNull();
  });

  it("reads a shasum line for the right file only", () => {
    const hex = "a".repeat(64);
    expect(parseSha256File(`${hex}  Sauri-0.1.1-mac-arm64.zip\n`, "Sauri-0.1.1-mac-arm64.zip")).toBe(hex);
    expect(parseSha256File(`${hex}  other.zip\n`, "Sauri-0.1.1-mac-arm64.zip")).toBeNull();
    expect(parseSha256File("nonsense", "Sauri-0.1.1-mac-arm64.zip")).toBeNull();
  });
});

describe("where the updater may go", () => {
  it("stays off without a download place and reads the feed from GitHub by default", () => {
    expect(releaseSource({})).toBeNull();
    expect(releasesRepo({ SAURI_RELEASES_REPO: "not a repo" })).toBe("");
    expect(releaseSource({ SAURI_RELEASES_REPO: REPO })).toEqual({
      repo: REPO,
      feedUrl: `https://api.github.com/repos/${REPO}/releases?per_page=20`,
      loopback: false,
    });
  });

  it("takes a loopback feed only with the test switch", () => {
    const env = { SAURI_RELEASES_REPO: REPO, SAURI_UPDATE_FEED_URL: "http://127.0.0.1:9000/feed.json" };
    expect(releaseSource(env)?.feedUrl).toContain("api.github.com");
    expect(releaseSource({ ...env, SAURI_ALLOW_LOOPBACK_DOWNLOADS: "1" })?.feedUrl).toBe("http://127.0.0.1:9000/feed.json");
    expect(releaseSource({ ...env, SAURI_ALLOW_LOOPBACK_DOWNLOADS: "1", SAURI_UPDATE_FEED_URL: "https://evil.example/feed" })?.feedUrl)
      .toContain("api.github.com");
  });

  it.each([
    [`https://api.github.com/repos/${REPO}/releases?per_page=20`, true],
    [`https://github.com/${REPO}/releases/download/v0.1.1/Sauri-0.1.1-mac-arm64.zip`, true],
    ["https://release-assets.githubusercontent.com/github-production-release-asset/1/x?sig=y", true],
    ["https://api.github.com/repos/other/repo/releases", false],
    ["https://api.github.com/user", false],
    [`https://github.com/other/repo/releases/download/v0.1.1/x.zip`, false],
    [`https://github.com/${REPO}/releases/download/../../x`, false],
    ["https://objects.githubusercontent.com/x", false],
    [`http://github.com/${REPO}/releases/download/v0.1.1/x.zip`, false],
    [`https://evil.example/${REPO}/releases/download/v0.1.1/x.zip`, false],
    [`https://user:pw@github.com/${REPO}/releases/download/v0.1.1/x.zip`, false],
    [`http://127.0.0.1:9000/${REPO}/releases/download/v0.1.1/x.zip`, false],
  ])("%s → %s", (url, allowed) => {
    const source = releaseSource({ SAURI_RELEASES_REPO: REPO }) as ReleaseSource;
    expect(allowedUrl(source, url)).toBe(allowed);
  });
});

/** Plays GitHub Releases on 127.0.0.1: the feed, the zip and its .sha256. */
async function releaseServer(files: Record<string, Buffer | string>, opts: { redirectTo?: string; ignoreRange?: boolean } = {}) {
  const seen: { path: string; range?: string; headers: http.IncomingHttpHeaders }[] = [];
  const server = http.createServer((request, response) => {
    seen.push({ path: request.url ?? "", range: request.headers.range, headers: request.headers });
    const name = (request.url ?? "").split("/").pop() ?? "";
    if (opts.redirectTo && name.endsWith(".zip")) {
      response.writeHead(302, { Location: opts.redirectTo }).end();
      return;
    }
    const body = files[name];
    if (body === undefined) {
      response.writeHead(404).end();
      return;
    }
    const data = Buffer.from(body);
    const range = /^bytes=(\d+)-$/.exec(request.headers.range ?? "");
    if (range && !opts.ignoreRange) {
      const start = Number(range[1]);
      response.writeHead(206, { "Content-Length": data.length - start, "Content-Range": `bytes ${start}-${data.length - 1}/${data.length}` });
      response.end(data.subarray(start));
      return;
    }
    response.writeHead(200, { "Content-Length": data.length }).end(data);
  });
  await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
  const base = `http://127.0.0.1:${(server.address() as AddressInfo).port}`;
  const source: ReleaseSource = { repo: REPO, feedUrl: `${base}/feed.json`, loopback: true };
  return { server, base, source, seen };
}

function releaseFor(base: string, version: string, zip: Buffer, sum: string): Release {
  const url = (name: string) => `${base}/${REPO}/releases/download/v${version}/${name}`;
  return {
    version,
    zip: { name: zipName(version), url: url(zipName(version)), size: zip.length },
    sha256: { name: `${zipName(version)}.sha256`, url: url(`${zipName(version)}.sha256`), size: Buffer.byteLength(sum) },
  };
}

function zipOf(version: string): Buffer {
  const at = path.join(dir, `build-${version}`);
  const app = fakeApp(at, version);
  const zip = path.join(dir, zipName(version));
  execFileSync("/usr/bin/ditto", ["-c", "-k", "--keepParent", app, zip]);
  return fs.readFileSync(zip);
}

const shaLine = (data: Buffer, name: string) => `${createHash("sha256").update(data).digest("hex")}  ${name}\n`;

describe("download and staging", () => {
  it("downloads, verifies and unpacks a newer version, sending no cookie or token", async () => {
    const zip = zipOf("0.1.1");
    const sum = shaLine(zip, zipName("0.1.1"));
    const { server, base, source, seen } = await releaseServer({ [zipName("0.1.1")]: zip, [`${zipName("0.1.1")}.sha256`]: sum });
    try {
      const updates = path.join(dir, "updates");
      const staged = await stageRelease(source, releaseFor(base, "0.1.1", zip, sum), updates);
      expect(staged.version).toBe("0.1.1");
      expect(fs.existsSync(path.join(staged.appPath, "Contents", "MacOS", "Sauri"))).toBe(true);
      expect(readStaged(updates)).toEqual(staged);
      for (const request of seen) {
        expect(request.headers.cookie).toBeUndefined();
        expect(request.headers.authorization).toBeUndefined();
        expect(request.headers["user-agent"]).toBe("Sauri-Desktop");
      }
      expect(fs.readdirSync(path.dirname(staged.zipPath)).filter((name) => name.endsWith(".part"))).toEqual([]);
    } finally {
      server.close();
    }
  });

  it("refuses a zip that does not match its .sha256 and keeps nothing of it", async () => {
    const zip = zipOf("0.1.1");
    const wrong = `${"0".repeat(64)}  ${zipName("0.1.1")}\n`;
    const { server, base, source } = await releaseServer({ [zipName("0.1.1")]: zip, [`${zipName("0.1.1")}.sha256`]: wrong });
    try {
      const updates = path.join(dir, "updates");
      await expect(stageRelease(source, releaseFor(base, "0.1.1", zip, wrong), updates)).rejects.toMatchObject({ code: "sha256_mismatch" });
      const left = fs.readdirSync(path.join(updates, "0.1.1"));
      expect(left.filter((name) => name.endsWith(".zip") || name.endsWith(".part") || name === "app")).toEqual([]);
      expect(readStaged(updates)).toBeNull();
    } finally {
      server.close();
    }
  });

  it("resumes a partial download with a Range request", async () => {
    const zip = zipOf("0.1.1");
    const sum = shaLine(zip, zipName("0.1.1"));
    const { server, base, source, seen } = await releaseServer({ [zipName("0.1.1")]: zip, [`${zipName("0.1.1")}.sha256`]: sum });
    try {
      const updates = path.join(dir, "updates");
      fs.mkdirSync(path.join(updates, "0.1.1"), { recursive: true });
      fs.writeFileSync(path.join(updates, "0.1.1", `${zipName("0.1.1")}.part`), zip.subarray(0, 100));
      await stageRelease(source, releaseFor(base, "0.1.1", zip, sum), updates);
      expect(seen.find((request) => request.path.endsWith(".zip"))?.range).toBe("bytes=100-");
    } finally {
      server.close();
    }
  });

  it("refuses a redirect off the allow-list and a body larger than the feed said", async () => {
    const zip = zipOf("0.1.1");
    const sum = shaLine(zip, zipName("0.1.1"));
    const elsewhere = await releaseServer({ [zipName("0.1.1")]: zip, [`${zipName("0.1.1")}.sha256`]: sum }, { redirectTo: "http://localhost:1/x.zip" });
    try {
      const release = releaseFor(elsewhere.base, "0.1.1", zip, sum);
      await expect(stageRelease(elsewhere.source, release, path.join(dir, "u1"))).rejects.toMatchObject({ code: "redirect_not_allowed" });
    } finally {
      elsewhere.server.close();
    }
    const big = await releaseServer({ [zipName("0.1.1")]: Buffer.concat([zip, Buffer.alloc(10)]), [`${zipName("0.1.1")}.sha256`]: sum });
    try {
      const release = releaseFor(big.base, "0.1.1", zip, sum);
      await expect(stageRelease(big.source, release, path.join(dir, "u2"))).rejects.toBeInstanceOf(UpdateError);
      expect(fs.readdirSync(path.join(dir, "u2", "0.1.1")).filter((name) => name.endsWith(".zip"))).toEqual([]);
    } finally {
      big.server.close();
    }
  });
});

describe("applying a version (Property 10)", () => {
  interface Setup {
    databaseDir: string;
    pgdata: string;
    current: string;
    staged: Staged;
    before: { pgdata: string; app: string };
    calls: string[];
    deps: ApplyDeps;
  }

  function setup(overrides: Partial<ApplyDeps> = {}): Setup {
    const databaseDir = path.join(dir, "Base de datos");
    const pgdata = path.join(databaseDir, "pgdata");
    fs.mkdirSync(path.join(pgdata, "base", "1"), { recursive: true });
    fs.writeFileSync(path.join(pgdata, "PG_VERSION"), "16\n");
    fs.writeFileSync(path.join(pgdata, "base", "1", "1259"), Buffer.alloc(8192, 7), { mode: 0o600 });
    fs.mkdirSync(path.join(databaseDir, "backups", "pgdata-0.0.9"), { recursive: true });
    const current = fakeApp(path.join(dir, "Applications"), "0.1.0");
    const stagedApp = fakeApp(path.join(dir, "updates", "0.1.1", "app"), "0.1.1");
    const staged: Staged = { version: "0.1.1", appPath: stagedApp, zipPath: path.join(dir, "updates", "0.1.1", "x.zip"), sha256: "" };
    const calls: string[] = [];
    const deps: ApplyDeps = {
      processing: async () => 0,
      stopServices: async () => void calls.push("stop"),
      startDatabase: async () => void calls.push("db-start"),
      stopDatabase: async () => void calls.push("db-stop"),
      migrate: async () => {
        calls.push("migrate");
        return true;
      },
      restartServices: async () => void calls.push("restart"),
      swap: swapBundle,
      applied: (version) => void calls.push(`applied ${version}`),
      relaunch: () => void calls.push("relaunch"),
      log: () => undefined,
      ...overrides,
    };
    return { databaseDir, pgdata, current, staged, before: { pgdata: treeDigest(pgdata), app: treeDigest(current) }, calls, deps };
  }

  const apply = (s: Setup, writable = true) =>
    applyUpdate({ staged: s.staged, bundle: { path: s.current, writable }, databaseDir: s.databaseDir, fromVersion: "0.1.0", deps: s.deps });

  it("refuses while meetings are being processed, without stopping anything", async () => {
    const s = setup({ processing: async () => 2 });
    expect(await apply(s)).toEqual({ ok: false, reason: "processing", count: 2 });
    expect(s.calls).toEqual([]);
    const unknown = setup({ processing: async () => null });
    expect(await apply(unknown)).toEqual({ ok: false, reason: "status_unavailable" });
    expect(treeDigest(s.current)).toBe(s.before.app);
  });

  it("does not migrate when the app cannot be replaced, and points to the verified zip", async () => {
    const s = setup();
    expect(await apply(s, false)).toEqual({ ok: false, reason: "not_writable", detail: s.staged.zipPath });
    expect(s.calls).toEqual([]);
  });

  it("restores pgdata exactly and keeps the old app when the new migration fails", async () => {
    const s = setup();
    s.deps.migrate = async () => {
      // A migration that changed the data before failing.
      fs.writeFileSync(path.join(s.pgdata, "base", "1", "1259"), Buffer.alloc(8192, 9));
      fs.writeFileSync(path.join(s.pgdata, "base", "1", "16384"), "new table");
      return false;
    };
    expect(await apply(s)).toEqual({ ok: false, reason: "migration_failed" });
    expect(treeDigest(s.pgdata)).toBe(s.before.pgdata);
    expect(treeDigest(backupDir(s.databaseDir, "0.1.0"))).toBe(s.before.pgdata);
    expect(treeDigest(s.current)).toBe(s.before.app);
    expect(fs.existsSync(s.staged.appPath)).toBe(true);
    expect(s.calls).toEqual(["stop", "db-start", "db-stop", "restart"]);
  });

  it("with a staged core whose alembic fails on purpose, through the real migration runner", async () => {
    const s = setup();
    // The staged app's own Python and psql: psql says the database exists, "alembic" writes into pgdata and fails.
    const layout = bundleLayout(s.staged.appPath);
    const write = (file: string, body: string) => {
      fs.mkdirSync(path.dirname(file), { recursive: true });
      fs.writeFileSync(file, `#!/bin/sh\n${body}\n`, { mode: 0o755 });
    };
    write(path.join(layout.runtimeDir, "pg", "bin", "psql"), "echo 1");
    write(
      path.join(layout.runtimeDir, "python", "bin", "python3"),
      `echo broken > '${path.join(s.pgdata, "base", "1", "1259")}'\necho 'alembic: migration failed on purpose' >&2\nexit 1`,
    );
    const paths = appPaths({ dev: true, home: path.join(dir, "home") });
    ensureSecrets(paths);
    const ctx: ServiceContext = {
      layout,
      paths,
      folders: { ...defaultFolders(paths), database: s.databaseDir },
      ports: portPlan(18200),
      localUserId: "6f1c2a52-3b2e-4a55-9d5b-1d2f3e4a5b6c",
    };
    const log = new RotatingLog(path.join(dir, "update.log"));
    s.deps.migrate = async () => {
      try {
        await prepareDatabase(ctx, log);
        return true;
      } catch {
        return false;
      }
    };
    expect(await apply(s)).toEqual({ ok: false, reason: "migration_failed" });
    log.close();
    expect(fs.readFileSync(path.join(dir, "update.log"), "utf8")).toContain("migration failed on purpose");
    expect(treeDigest(s.pgdata)).toBe(s.before.pgdata);
    expect(treeDigest(s.current)).toBe(s.before.app);
  });

  it("swaps the app after a good migration, keeps only the last pgdata copy and relaunches", async () => {
    const s = setup();
    const result = await apply(s);
    expect(result).toEqual({ ok: true, version: "0.1.1" });
    expect(fs.readFileSync(path.join(s.current, "Contents", "Resources", "build.json"), "utf8")).toContain("0.1.1");
    expect(fs.readdirSync(path.join(s.databaseDir, "backups"))).toEqual(["pgdata-0.1.0"]);
    expect(treeDigest(backupDir(s.databaseDir, "0.1.0"))).toBe(s.before.pgdata);
    expect(fs.readdirSync(path.dirname(s.current)).sort()).toEqual(["Sauri.app"]);
    expect(s.calls).toEqual(["stop", "db-start", "migrate", "db-stop", "applied 0.1.1", "relaunch"]);
  });

  it("puts everything back when the new app cannot be moved in", async () => {
    const s = setup();
    s.deps.migrate = async () => {
      fs.writeFileSync(path.join(s.pgdata, "base", "1", "1259"), "migrated");
      return true;
    };
    fs.rmSync(s.staged.appPath, { recursive: true, force: true }); // nothing to move in
    expect(await apply(s)).toEqual({ ok: false, reason: "swap_failed" });
    expect(treeDigest(s.current)).toBe(s.before.app);
    expect(treeDigest(s.pgdata)).toBe(s.before.pgdata);
    expect(s.calls.at(-1)).toBe("restart");
  });

  it("stops before touching anything when the copy cannot be made", async () => {
    const s = setup();
    fs.rmSync(s.pgdata, { recursive: true, force: true });
    const spy = vi.fn(async () => true);
    s.deps.migrate = spy;
    expect(await apply(s)).toEqual({ ok: false, reason: "backup_failed" });
    expect(spy).not.toHaveBeenCalled();
    expect(treeDigest(s.current)).toBe(s.before.app);
  });
});

describe("migrations on start (Requirement 9.3, Property 10)", () => {
  function data() {
    const databaseDir = path.join(dir, "Base de datos");
    const pgdata = path.join(databaseDir, "pgdata");
    fs.mkdirSync(path.join(pgdata, "base", "1"), { recursive: true });
    fs.writeFileSync(path.join(pgdata, "PG_VERSION"), "16\n");
    fs.writeFileSync(path.join(pgdata, "base", "1", "1259"), Buffer.alloc(8192, 7), { mode: 0o600 });
    fs.mkdirSync(path.join(databaseDir, "backups", "pgdata-0.0.9"), { recursive: true });
    return { databaseDir, pgdata, before: treeDigest(pgdata) };
  }

  function run(databaseDir: string, dataVersion: string | undefined, migrate: () => Promise<boolean>, databaseRunning = false) {
    const calls: string[] = [];
    const result = migrateOnStart({
      databaseDir,
      dataVersion,
      appVersion: "0.1.1",
      databaseRunning,
      startDatabase: async () => void calls.push("start"),
      stopDatabase: async () => void calls.push("stop"),
      migrate: async () => {
        calls.push("migrate");
        return migrate();
      },
      log: () => undefined,
    });
    return { result, calls };
  }

  it("makes no copy when the data already belongs to this version", async () => {
    const { databaseDir } = data();
    const { result, calls } = run(databaseDir, "0.1.1", async () => true);
    expect(await result).toEqual({ ok: true, backup: null });
    expect(fs.readdirSync(path.join(databaseDir, "backups"))).toEqual(["pgdata-0.0.9"]);
    expect(calls).toEqual(["start", "migrate"]);
  });

  it("makes no copy of a database that does not exist yet", async () => {
    const databaseDir = path.join(dir, "empty");
    const { result } = run(databaseDir, undefined, async () => true);
    expect(await result).toEqual({ ok: true, backup: null });
    expect(fs.existsSync(path.join(databaseDir, "backups"))).toBe(false);
  });

  it("copies the stopped data before migrating to a new version, keeping only that copy", async () => {
    const { databaseDir, before } = data();
    const { result, calls } = run(databaseDir, "0.1.0", async () => true, true);
    expect(await result).toEqual({ ok: true, backup: backupDir(databaseDir, "0.1.0") });
    expect(fs.readdirSync(path.join(databaseDir, "backups"))).toEqual(["pgdata-0.1.0"]);
    expect(treeDigest(backupDir(databaseDir, "0.1.0"))).toBe(before);
    expect(calls).toEqual(["stop", "start", "migrate"]);
  });

  it("restores the copy and starts nothing when the migration fails", async () => {
    const { databaseDir, pgdata, before } = data();
    const { result, calls } = run(databaseDir, undefined, async () => {
      fs.writeFileSync(path.join(pgdata, "base", "1", "1259"), "half migrated");
      fs.writeFileSync(path.join(pgdata, "base", "1", "16384"), "new table");
      return false;
    });
    expect(await result).toEqual({ ok: false, reason: "migration_failed", restored: true });
    expect(treeDigest(pgdata)).toBe(before);
    expect(treeDigest(backupDir(databaseDir, "unknown"))).toBe(before);
    expect(calls).toEqual(["start", "migrate", "stop"]);
  });
});
