import { createHash } from "node:crypto";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { type AppConfig, defaultConfig } from "./config.ts";
import { MARKER_FILE, readMarker, type UserFolders, writeMarker } from "./paths.ts";
import { checkTarget, copyAndVerify, folderUsage, PART_SUFFIX, relocate, type RelocateDeps } from "./relocate.ts";

let dir: string;

beforeEach(() => {
  dir = fs.mkdtempSync(path.join(os.tmpdir(), "sauri-relocate-"));
});

afterEach(() => {
  for (const entry of fs.readdirSync(dir, { recursive: true }) as string[]) {
    const file = path.join(dir, entry);
    if (!fs.lstatSync(file).isSymbolicLink()) fs.chmodSync(file, 0o700);
  }
  fs.rmSync(dir, { recursive: true, force: true });
});

/** Small deterministic generator, so a failing tree can be rebuilt from its seed. */
function random(seed: number): () => number {
  let state = seed >>> 0;
  return () => {
    state = (state * 1664525 + 1013904223) >>> 0;
    return state / 2 ** 32;
  };
}

function randomTree(root: string, seed: number): void {
  const next = random(seed);
  const names = ["audio", "video", "thumbs", "pg data", "base", "global", "a.b", "x"];
  const grow = (current: string, depth: number) => {
    fs.mkdirSync(current, { recursive: true });
    const files = Math.floor(next() * 6);
    for (let index = 0; index < files; index += 1) {
      const size = next() < 0.2 ? 0 : Math.floor(next() * 300_000);
      const bytes = Buffer.alloc(size);
      for (let at = 0; at < size; at += 1) bytes[at] = Math.floor(next() * 256);
      fs.writeFileSync(path.join(current, `file ${index}-${Math.floor(next() * 1000)}.bin`), bytes);
    }
    if (depth >= 3) return;
    const children = Math.floor(next() * 3);
    for (let index = 0; index < children; index += 1) {
      grow(path.join(current, `${names[Math.floor(next() * names.length)]} ${depth}${index}`), depth + 1);
    }
  };
  grow(root, 0);
}

/** relative path -> "size:sha256" for every file except the marker. */
function snapshot(root: string): Record<string, string> {
  const result: Record<string, string> = {};
  for (const entry of fs.readdirSync(root, { recursive: true }) as string[]) {
    const file = path.join(root, entry);
    if (entry === MARKER_FILE || !fs.statSync(file).isFile()) continue;
    const content = fs.readFileSync(file);
    result[entry.split(path.sep).join("/")] = `${content.length}:${createHash("sha256").update(content).digest("hex")}`;
  }
  return result;
}

function emptyDirs(root: string): string[] {
  return (fs.readdirSync(root, { recursive: true }) as string[])
    .filter((entry) => fs.statSync(path.join(root, entry)).isDirectory() && fs.readdirSync(path.join(root, entry)).length === 0)
    .sort();
}

describe("copyAndVerify (property 9)", () => {
  it("leaves every file at the same relative path with the same size and SHA-256, for random trees", async () => {
    for (let seed = 1; seed <= 25; seed += 1) {
      const source = path.join(dir, `source-${seed}`);
      const target = path.join(dir, `target-${seed}`);
      randomTree(source, seed);
      const before = snapshot(source);
      const copied = await copyAndVerify(source, target);
      expect(snapshot(target), `seed ${seed}`).toEqual(before);
      expect(snapshot(source), `seed ${seed}`).toEqual(before);
      expect(copied.length).toBe(Object.keys(before).length);
      expect(emptyDirs(target)).toEqual(emptyDirs(source));
      expect((fs.readdirSync(target, { recursive: true }) as string[]).some((name) => name.endsWith(PART_SUFFIX))).toBe(false);
    }
  });

  it("resumes an interrupted copy, replacing a half-written .part file", async () => {
    const source = path.join(dir, "source");
    const target = path.join(dir, "target");
    randomTree(source, 99);
    for (const name of ["a", "b", "c", "d"]) fs.writeFileSync(path.join(source, `${name}.bin`), name.repeat(5000));
    const before = snapshot(source);
    // Files are copied in this order.
    const order = Object.keys(before).sort((a, b) => a.localeCompare(b));
    const first = order[0];
    const stopAt = order[2];
    await expect(
      copyAndVerify(source, target, {
        beforeFile: (entry) => {
          if (entry.relative === stopAt) throw new Error("killed");
        },
      }),
    ).rejects.toThrow("killed");
    fs.writeFileSync(path.join(target, `${stopAt}${PART_SUFFIX}`), "half");
    const firstMtime = fs.statSync(path.join(target, first)).mtimeMs;
    await copyAndVerify(source, target);
    expect(snapshot(target)).toEqual(before);
    // Already complete files are kept, not copied again.
    expect(fs.statSync(path.join(target, first)).mtimeMs).toBe(firstMtime);
    expect((fs.readdirSync(target, { recursive: true }) as string[]).some((name) => name.endsWith(PART_SUFFIX))).toBe(false);
  });

  it("fails verification when a copied file changes before the check", async () => {
    const source = path.join(dir, "source");
    const target = path.join(dir, "target");
    fs.mkdirSync(source);
    fs.writeFileSync(path.join(source, "a.bin"), "aaaa");
    fs.writeFileSync(path.join(source, "b.bin"), "bbbb");
    await expect(
      copyAndVerify(source, target, {
        beforeFile: (entry) => {
          if (entry.relative === "b.bin") fs.writeFileSync(path.join(target, "a.bin"), "AAAA");
        },
      }),
    ).rejects.toMatchObject({ code: "verify_failed", detail: "a.bin" });
  });

  it("keeps the permission bits PostgreSQL requires", async () => {
    const source = path.join(dir, "source");
    fs.mkdirSync(path.join(source, "pgdata"), { recursive: true });
    fs.chmodSync(path.join(source, "pgdata"), 0o700);
    fs.writeFileSync(path.join(source, "pgdata", "PG_VERSION"), "16\n", { mode: 0o600 });
    const target = path.join(dir, "target");
    await copyAndVerify(source, target);
    expect(fs.statSync(path.join(target, "pgdata")).mode & 0o777).toBe(0o700);
    expect(fs.statSync(path.join(target, "pgdata", "PG_VERSION")).mode & 0o777).toBe(0o600);
  });

  it("refuses links instead of copying what they point to", async () => {
    const source = path.join(dir, "source");
    fs.mkdirSync(source);
    fs.writeFileSync(path.join(dir, "outside.txt"), "outside");
    fs.symlinkSync(path.join(dir, "outside.txt"), path.join(source, "link"));
    await expect(copyAndVerify(source, path.join(dir, "target"))).rejects.toMatchObject({ code: "unsupported_file" });
  });
});

function installation(): { config: AppConfig; folders: UserFolders } {
  const config = defaultConfig();
  const folders: UserFolders = {
    recordings: path.join(dir, "Sauri", "Recordings"),
    database: path.join(dir, "Sauri", "Database"),
    models: path.join(dir, "Sauri", "Models"),
  };
  for (const [kind, folder] of Object.entries(folders)) {
    fs.mkdirSync(folder, { recursive: true });
    writeMarker(folder, { installId: config.installId, kind: kind as keyof UserFolders });
  }
  randomTree(path.join(folders.recordings, "meetings"), 7);
  return { config: { ...config, setupStep: "done", localUserId: "u", paths: folders }, folders };
}

function deps(state: { config: AppConfig }, overrides: Partial<RelocateDeps> = {}) {
  const calls: string[] = [];
  const value: RelocateDeps = {
    config: () => state.config,
    update: (change) => {
      state.config = { ...state.config, ...change };
      return state.config;
    },
    processing: async () => 0,
    chooseFolder: async () => path.join(dir, "External", "Recordings"),
    confirmTrash: async () => false,
    trash: vi.fn(async () => undefined),
    stopServices: async () => {
      calls.push("stop");
    },
    startServices: async () => {
      calls.push(`start:${state.config.paths?.recordings}`);
    },
    log: () => undefined,
    ...overrides,
  };
  return { deps: value, calls };
}

describe("relocate", () => {
  it("refuses while meetings are processed and says how many, before any dialog or stop", async () => {
    const state = installation();
    const choose = vi.fn(async () => path.join(dir, "elsewhere"));
    const { deps: d, calls } = deps(state, { processing: async () => 2, chooseFolder: choose });
    expect(await relocate("recordings", d)).toEqual({ ok: false, reason: "processing", count: 2 });
    expect(choose).not.toHaveBeenCalled();
    expect(calls).toEqual([]);
  });

  it("refuses when the core cannot say what is in progress", async () => {
    const state = installation();
    const { deps: d, calls } = deps(state, { processing: async () => null });
    expect(await relocate("recordings", d)).toEqual({ ok: false, reason: "status_unavailable" });
    expect(calls).toEqual([]);
  });

  it("refuses when a meeting starts while the folder dialog is open", async () => {
    const state = installation();
    const counts = [0, 1];
    const { deps: d, calls } = deps(state, { processing: async () => counts.shift() ?? 0 });
    expect(await relocate("recordings", d)).toEqual({ ok: false, reason: "processing", count: 1 });
    expect(calls).toEqual([]);
  });

  it("moves, verifies, switches config, restarts, and keeps the old folder until the owner confirms", async () => {
    const state = installation();
    const previous = state.folders.recordings;
    const before = snapshot(previous);
    const target = path.join(dir, "External", "Recordings");
    const { deps: d, calls } = deps(state);
    const result = await relocate("recordings", d);
    expect(result).toEqual({ ok: true, kind: "recordings", path: target, previous, previousTrashed: false });
    expect(calls).toEqual(["stop", `start:${target}`]);
    expect(state.config.paths).toEqual({ ...state.folders, recordings: target });
    expect(snapshot(target)).toEqual(before);
    expect(snapshot(previous)).toEqual(before);
    expect(readMarker(target)).toEqual({ installId: state.config.installId, kind: "recordings" });
    expect(d.trash).not.toHaveBeenCalled();
  });

  it("moves the old folder to the Trash only after the confirmation, once the new one is in use", async () => {
    const state = installation();
    const previous = state.folders.recordings;
    const order: string[] = [];
    const { deps: d } = deps(state, {
      startServices: async () => {
        order.push("start");
      },
      confirmTrash: async (_kind, folder) => {
        order.push(`ask:${folder}`);
        return true;
      },
      trash: vi.fn(async (folder: string) => {
        order.push(`trash:${folder}`);
      }),
    });
    const result = await relocate("recordings", d);
    expect(result).toMatchObject({ ok: true, previousTrashed: true });
    expect(order).toEqual(["start", `ask:${previous}`, `trash:${previous}`]);
  });

  it("an interrupted copy leaves the old folder and config untouched, restarts on it, and can be resumed", async () => {
    const state = installation();
    const previous = state.folders.recordings;
    const before = snapshot(previous);
    const original = state.config;
    let seen = 0;
    const { deps: d, calls } = deps(state, {
      hooks: {
        beforeFile: () => {
          seen += 1;
          if (seen === 3) throw new Error("disk unplugged");
        },
      },
    });
    const failed = await relocate("recordings", d);
    expect(failed).toMatchObject({ ok: false, reason: "copy_failed" });
    expect(state.config).toBe(original);
    expect(calls).toEqual(["stop", `start:${previous}`]);
    expect(snapshot(previous)).toEqual(before);
    expect(d.trash).not.toHaveBeenCalled();

    const retry = deps(state);
    expect(await relocate("recordings", retry.deps)).toMatchObject({ ok: true });
    expect(snapshot(path.join(dir, "External", "Recordings"))).toEqual(before);
    expect(snapshot(previous)).toEqual(before);
  });

  it("cancelling the folder dialog changes nothing", async () => {
    const state = installation();
    const { deps: d, calls } = deps(state, { chooseFolder: async () => null });
    expect(await relocate("recordings", d)).toEqual({ ok: false, reason: "cancelled" });
    expect(calls).toEqual([]);
  });
});

describe("checkTarget", () => {
  it("refuses the same folder, nested folders, another kind's folder and non-empty foreign folders", () => {
    const { config, folders } = installation();
    const id = config.installId;
    expect(checkTarget("recordings", folders, folders.recordings, id)).toEqual({ issue: "same" });
    expect(checkTarget("recordings", folders, path.join(folders.recordings, "inner"), id)).toEqual({ issue: "nested" });
    expect(checkTarget("recordings", folders, path.dirname(folders.recordings), id)).toEqual({ issue: "nested" });
    expect(checkTarget("recordings", folders, path.join(folders.models, "rec"), id)).toEqual({ issue: "duplicate" });
    const busy = path.join(dir, "Documents");
    fs.mkdirSync(busy);
    fs.writeFileSync(path.join(busy, "taxes.pdf"), "x");
    expect(checkTarget("recordings", folders, busy, id)).toEqual({ issue: "not_empty" });
    const foreign = path.join(dir, "Other");
    fs.mkdirSync(foreign);
    writeMarker(foreign, { installId: "another", kind: "recordings" });
    expect(checkTarget("recordings", folders, foreign, id)).toEqual({ issue: "foreign" });
    expect(checkTarget("recordings", folders, path.join(dir, "Fresh", "Recordings"), id)).toBeNull();
  });

  it("refuses a folder Sauri cannot write to", () => {
    const { config, folders } = installation();
    const locked = path.join(dir, "Locked");
    fs.mkdirSync(locked);
    fs.chmodSync(locked, 0o500);
    expect(checkTarget("recordings", folders, path.join(locked, "Recordings"), config.installId)).toEqual({
      issue: "not_writable",
    });
  });

  it("refuses a disk without room for the data", async () => {
    const { config, folders } = installation();
    const hardware = await import("./hardware.ts");
    const spy = vi.spyOn(hardware, "freeBytes").mockReturnValue(10);
    try {
      const result = checkTarget("recordings", folders, path.join(dir, "Small"), config.installId);
      expect(result).toMatchObject({ issue: "no_space", freeBytes: 10 });
      expect(result?.neededBytes).toBeGreaterThan(10);
    } finally {
      spy.mockRestore();
    }
  });
});

describe("folderUsage", () => {
  it("reports the size of each folder and the free space of its disk, or nothing for a missing one", () => {
    const { folders } = installation();
    fs.rmSync(folders.models, { recursive: true });
    const usage = folderUsage(folders);
    const recordings = usage.find((item) => item.kind === "recordings");
    const expected = Object.values(snapshot(folders.recordings)).reduce((total, value) => total + Number(value.split(":")[0]), 0);
    expect(recordings?.usedBytes).toBeGreaterThanOrEqual(expected);
    expect(recordings?.freeBytes).toBeGreaterThan(0);
    expect(usage.find((item) => item.kind === "models")).toEqual({ kind: "models", path: folders.models, usedBytes: null, freeBytes: null });
  });
});
