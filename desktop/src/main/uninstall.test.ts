import { spawnSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { appPaths, type AppPaths, defaultFolders, type UserFolders, writeMarker } from "./paths.ts";
import {
  afterExitSweep,
  appBundleOf,
  checkUserFolder,
  type FolderTarget,
  internalPaths,
  planUninstall,
  removeOwnedTree,
  runUninstall,
  treeBytes,
  type UninstallDeps,
  UninstallError,
} from "./uninstall.ts";

const INSTALL = "11111111-2222-4333-8444-555555555555";
const APP_ID = "com.sauri.desktop";
let root: string;
let home: string;
let outside: string;
let paths: AppPaths;
let folders: UserFolders;

function write(file: string, content = "x"): void {
  fs.mkdirSync(path.dirname(file), { recursive: true });
  fs.writeFileSync(file, content);
}

/** Every file and folder under `dir` with its content, to prove a tree was left untouched. */
function snapshot(dir: string): Record<string, string> {
  const result: Record<string, string> = {};
  for (const rel of fs.readdirSync(dir, { recursive: true }) as string[]) {
    const file = path.join(dir, rel);
    const info = fs.lstatSync(file);
    result[rel] = info.isSymbolicLink() ? `link:${fs.readlinkSync(file)}` : info.isFile() ? fs.readFileSync(file, "utf8") : "dir";
  }
  return result;
}

beforeEach(() => {
  root = fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(), "sauri-uninstall-")));
  home = path.join(root, "home");
  outside = path.join(root, "outside");
  paths = appPaths({ dev: false, home });
  folders = defaultFolders({ home, dev: false });
  // An installation as the app leaves it.
  write(paths.configFile, "{}");
  write(path.join(paths.secretsDir, "local_token"), "secret");
  write(path.join(paths.electronDir, "Local State"), "{}");
  write(path.join(paths.enginesDir, "parakeet", "model.bin"), "12345");
  write(path.join(paths.logsDir, "api.log"), "log");
  write(path.join(home, "Library", "Preferences", `${APP_ID}.plist`), "plist");
  for (const kind of ["recordings", "database", "models"] as const) {
    fs.mkdirSync(folders[kind], { recursive: true });
    writeMarker(folders[kind], { installId: INSTALL, kind });
  }
  write(path.join(folders.recordings, "recordings", "m1", "audio.webm"), "audio-bytes");
  write(path.join(folders.database, "pgdata", "PG_VERSION"), "16");
  // Things that are not Sauri's: a sibling app's data and a folder outside the home.
  write(path.join(home, "Library", "Application Support", "Other", "keep.txt"), "keep");
  write(path.join(home, "Library", "Logs", "Other", "keep.log"), "keep");
  write(path.join(outside, "precious.txt"), "precious");
  // Links inside internal paths that point outside: removed as links, their targets never visited.
  fs.symlinkSync(outside, path.join(paths.enginesDir, "escape-dir"));
  fs.symlinkSync(path.join(outside, "precious.txt"), path.join(paths.dataDir, "escape-file"));
});

afterEach(() => {
  fs.rmSync(root, { recursive: true, force: true });
});

interface Fake extends UninstallDeps {
  trashed: string[];
  stopped: number;
}

function deps(overrides: Partial<UninstallDeps> = {}): Fake {
  const fake: Fake = {
    trashed: [],
    stopped: 0,
    plan: () => planUninstall({ paths, folders, installId: INSTALL, appId: APP_ID, appBundle: null }),
    processing: async () => 0,
    confirm: async () => ({ proceed: true, removeApp: false }),
    confirmProcessing: async () => true,
    trashFolders: async () => false,
    stopServices: async () => {
      fake.stopped += 1;
    },
    trash: async (target) => {
      // Stands in for shell.trashItem: moves the item aside, as the Trash does.
      const dest = path.join(root, "Trash", path.basename(target));
      fs.mkdirSync(path.dirname(dest), { recursive: true });
      fs.renameSync(target, dest);
      fake.trashed.push(target);
    },
  };
  return Object.assign(fake, overrides);
}

describe("internal paths", () => {
  it("lists only Sauri's own locations under ~/Library", () => {
    const list = internalPaths(paths, APP_ID);
    expect(list).toContain(path.join(home, "Library", "Application Support", "Sauri"));
    expect(list).toContain(path.join(home, "Library", "Logs", "Sauri"));
    for (const item of list) expect(item.startsWith(path.join(home, "Library") + path.sep)).toBe(true);
    expect(internalPaths(paths)).toHaveLength(2);
  });

  it("removes a tree without following links that leave it", () => {
    removeOwnedTree(paths.dataDir);
    expect(fs.existsSync(paths.dataDir)).toBe(false);
    expect(fs.readFileSync(path.join(outside, "precious.txt"), "utf8")).toBe("precious");
  });

  it("refuses a path that is itself a link", () => {
    const link = path.join(root, "link");
    fs.symlinkSync(outside, link);
    expect(() => removeOwnedTree(link)).toThrow(UninstallError);
    expect(fs.existsSync(path.join(outside, "precious.txt"))).toBe(true);
  });

  it("plans a link in place of the logs folder as refused, never as a target", () => {
    fs.rmSync(paths.logsDir, { recursive: true });
    fs.symlinkSync(outside, paths.logsDir);
    const plan = planUninstall({ paths, folders, installId: INSTALL, appBundle: null });
    expect(plan.refused).toEqual([paths.logsDir]);
    expect(plan.internal.map((item) => item.path)).toEqual([paths.dataDir]);
  });

  it("counts bytes without following links", () => {
    expect(treeBytes(path.join(paths.enginesDir))).toBe(5);
  });
});

describe("user folders", () => {
  it("accepts only folders with this installation's marker for their kind", () => {
    expect(checkUserFolder("recordings", folders.recordings, INSTALL, paths)).toBe("ok");
    expect(checkUserFolder("recordings", folders.recordings, "another-install", paths)).toBe("foreign");
    expect(checkUserFolder("models", folders.recordings, INSTALL, paths)).toBe("foreign");
    expect(checkUserFolder("recordings", outside, INSTALL, paths)).toBe("marker_missing");
    expect(checkUserFolder("recordings", path.join(root, "nope"), INSTALL, paths)).toBe("missing");
  });

  it("refuses links, protected locations and folders whose links escape", () => {
    const link = path.join(root, "linked");
    fs.symlinkSync(folders.recordings, link);
    expect(checkUserFolder("recordings", link, INSTALL, paths)).toBe("symlink");
    writeMarker(home, { installId: INSTALL, kind: "recordings" });
    expect(checkUserFolder("recordings", home, INSTALL, paths)).toBe("unsafe_location");
    expect(checkUserFolder("recordings", root, INSTALL, paths)).toBe("unsafe_location");
    fs.symlinkSync(outside, path.join(folders.models, "shortcut"));
    expect(checkUserFolder("models", folders.models, INSTALL, paths)).toBe("symlink_escape");
    fs.symlinkSync("recordings/m1", path.join(folders.recordings, "inner"));
    expect(checkUserFolder("recordings", folders.recordings, INSTALL, paths)).toBe("ok");
  });

  it("reports each folder's size", () => {
    const plan = planUninstall({ paths, folders, installId: INSTALL, appBundle: null });
    const recordings = plan.folders.find((item) => item.kind === "recordings") as FolderTarget;
    expect(recordings.bytes).toBe(treeBytes(folders.recordings));
    expect(recordings.bytes).toBeGreaterThan("audio-bytes".length);
  });
});

describe("app bundle", () => {
  it("is found only for the installed app", () => {
    const bundle = path.join(root, "Apps", "Sauri.app");
    fs.mkdirSync(path.join(bundle, "Contents", "MacOS"), { recursive: true });
    const exec = path.join(bundle, "Contents", "MacOS", "Sauri");
    expect(appBundleOf(exec, false)).toBeNull();
    expect(appBundleOf(exec, true)).toEqual({ path: bundle, writable: true });
    expect(appBundleOf(path.join(root, "bin", "x", "y", "electron"), true)).toBeNull();
    fs.chmodSync(path.join(root, "Apps"), 0o500);
    try {
      expect(appBundleOf(exec, true)?.writable).toBe(false);
    } finally {
      fs.chmodSync(path.join(root, "Apps"), 0o700);
    }
  });
});

describe("runUninstall", () => {
  it("keeps the user folders by default and touches nothing outside Sauri's paths", async () => {
    const before = snapshot(outside);
    const others = snapshot(path.join(home, "Library", "Application Support", "Other"));
    const userBefore = Object.fromEntries((["recordings", "database", "models"] as const).map((k) => [k, snapshot(folders[k])]));
    const d = deps();
    const report = await runUninstall(d);
    expect(report).not.toBeNull();
    expect(d.stopped).toBe(1);
    for (const item of internalPaths(paths, APP_ID)) expect(fs.existsSync(item)).toBe(false);
    expect(report?.failed).toEqual([]);
    expect(report?.kept).toEqual([folders.recordings, folders.database, folders.models]);
    for (const kind of ["recordings", "database", "models"] as const) expect(snapshot(folders[kind])).toEqual(userBefore[kind]);
    expect(snapshot(outside)).toEqual(before);
    expect(snapshot(path.join(home, "Library", "Application Support", "Other"))).toEqual(others);
    expect(fs.existsSync(path.join(home, "Library", "Logs", "Other", "keep.log"))).toBe(true);
    expect(d.trashed).toEqual([]);
  });

  it("moves the folders to the Trash only when the user says so", async () => {
    let shown: FolderTarget[] = [];
    const d = deps({
      trashFolders: async (list) => {
        shown = list;
        return true;
      },
    });
    const report = await runUninstall(d);
    expect(shown.map((item) => item.verdict)).toEqual(["ok", "ok", "ok"]);
    expect(report?.trashed).toEqual([folders.recordings, folders.database, folders.models]);
    for (const kind of ["recordings", "database", "models"] as const) expect(fs.existsSync(folders[kind])).toBe(false);
    expect(fs.readFileSync(path.join(root, "Trash", path.basename(folders.recordings), "recordings", "m1", "audio.webm"), "utf8")).toBe(
      "audio-bytes",
    );
  });

  it("never trashes a folder that fails its check, even when asked to", async () => {
    writeMarker(folders.models, { installId: "another-install", kind: "models" });
    const d = deps({ trashFolders: async () => true });
    const report = await runUninstall(d);
    expect(report?.trashed).toEqual([folders.recordings, folders.database]);
    expect(report?.kept).toEqual([folders.models]);
    expect(fs.existsSync(path.join(folders.models, ".sauri-folder"))).toBe(true);
  });

  it("does not ask about folders when none can be moved", async () => {
    let asked = false;
    for (const kind of ["recordings", "database", "models"] as const) fs.rmSync(path.join(folders[kind], ".sauri-folder"));
    await runUninstall(
      deps({
        trashFolders: async () => {
          asked = true;
          return true;
        },
      }),
    );
    expect(asked).toBe(false);
  });

  it("touches nothing when the user cancels", async () => {
    const d = deps({ confirm: async () => ({ proceed: false, removeApp: true }) });
    expect(await runUninstall(d)).toBeNull();
    expect(d.stopped).toBe(0);
    expect(fs.existsSync(paths.dataDir)).toBe(true);
  });

  it("asks before uninstalling while meetings are processed", async () => {
    let counted = 0;
    const d = deps({
      processing: async () => 2,
      confirmProcessing: async (count) => {
        counted = count;
        return false;
      },
    });
    expect(await runUninstall(d)).toBeNull();
    expect(counted).toBe(2);
    expect(fs.existsSync(paths.logsDir)).toBe(true);
  });

  it("moves the app to the Trash only when confirmed and writable", async () => {
    const bundle = path.join(root, "Apps", "Sauri.app");
    fs.mkdirSync(bundle, { recursive: true });
    const plan = () => planUninstall({ paths, folders, installId: INSTALL, appBundle: { path: bundle, writable: false } });
    const notWritable = await runUninstall(deps({ plan, confirm: async () => ({ proceed: true, removeApp: true }) }));
    expect(notWritable?.appRemoved).toBe(false);
    expect(fs.existsSync(bundle)).toBe(true);

    const d = deps({
      plan: () => planUninstall({ paths, folders, installId: INSTALL, appBundle: { path: bundle, writable: true } }),
      confirm: async () => ({ proceed: true, removeApp: true }),
    });
    const report = await runUninstall(d);
    expect(report?.appRemoved).toBe(true);
    expect(fs.existsSync(bundle)).toBe(false);
  });
});

describe("afterExitSweep", () => {
  it("removes the internal paths once the process is gone, and refuses links", () => {
    const link = path.join(root, "logs-link");
    fs.symlinkSync(outside, link);
    // A process that has already ended.
    const done = spawnSync("/usr/bin/true");
    const { command, args } = afterExitSweep(done.pid as number, [paths.dataDir, paths.logsDir, link]);
    const result = spawnSync(command, args, { timeout: 10_000 });
    expect(result.status).toBe(0);
    expect(fs.existsSync(paths.dataDir)).toBe(false);
    expect(fs.existsSync(paths.logsDir)).toBe(false);
    expect(fs.lstatSync(link).isSymbolicLink()).toBe(true);
    expect(fs.readFileSync(path.join(outside, "precious.txt"), "utf8")).toBe("precious");
  });
});
