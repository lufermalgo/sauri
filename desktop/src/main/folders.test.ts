import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { inspectFolder, inspectFolders, prepareFolders } from "./folders.ts";
import {
  appPaths,
  defaultFolders,
  folderProblems,
  MARKER_FILE,
  PathError,
  readMarker,
  socketPath,
  type UserFolders,
  writeMarker,
} from "./paths.ts";

let dir: string;
const INSTALL = "11111111-2222-4333-8444-555555555555";

beforeEach(() => {
  dir = fs.mkdtempSync(path.join(os.tmpdir(), "sauri-folders-"));
});

afterEach(() => {
  for (const entry of fs.readdirSync(dir, { recursive: true }) as string[]) {
    fs.chmodSync(path.join(dir, entry), 0o700);
  }
  fs.rmSync(dir, { recursive: true, force: true });
});

const folders = (): UserFolders => defaultFolders({ home: dir, dev: false });

describe("paths", () => {
  it("keeps development data apart from the real installation", () => {
    expect(appPaths({ dev: true, home: dir }).dataDir).toBe(path.join(dir, "Library", "Application Support", "Sauri-dev"));
    expect(appPaths({ dev: false, home: dir }).logsDir).toBe(path.join(dir, "Library", "Logs", "Sauri"));
    expect(defaultFolders({ home: dir, dev: false })).toEqual({
      recordings: path.join(dir, "Sauri", "Grabaciones"),
      database: path.join(dir, "Sauri", "Base de datos"),
      models: path.join(dir, "Sauri", "Modelos"),
    });
    expect(defaultFolders({ home: dir, dev: true }).models).toBe(path.join(dir, "Sauri-dev", "Modelos"));
  });

  it("fails clearly when the PostgreSQL socket path is too long for macOS", () => {
    expect(socketPath("/Users/ana/Library/Application Support/Sauri/run", 5432)).toMatch(/\.s\.PGSQL\.5432$/);
    expect(() => socketPath(`/Users/${"x".repeat(80)}/Library/Application Support/Sauri/run`, 5432)).toThrow(PathError);
  });

  it("names every missing, unmarked or foreign folder", () => {
    const paths = folders();
    fs.mkdirSync(paths.recordings, { recursive: true });
    writeMarker(paths.recordings, { installId: INSTALL, kind: "recordings" });
    fs.mkdirSync(paths.database, { recursive: true });
    fs.mkdirSync(paths.models, { recursive: true });
    writeMarker(paths.models, { installId: "another", kind: "models" });
    expect(folderProblems(paths, INSTALL)).toEqual([
      { kind: "database", path: paths.database, reason: "marker_missing" },
      { kind: "models", path: paths.models, reason: "foreign" },
    ]);
    fs.rmSync(paths.recordings, { recursive: true });
    expect(folderProblems(paths, INSTALL)[0]).toEqual({ kind: "recordings", path: paths.recordings, reason: "missing" });
  });
});

describe("folders", () => {
  it("shows the free space of the disk that will hold a folder not created yet", () => {
    const info = inspectFolder("recordings", path.join(dir, "a", "b", "Grabaciones"), INSTALL);
    expect(info.issue).toBeUndefined();
    expect(info.freeBytes).toBeGreaterThan(0);
  });

  it("rejects a folder without write permission", () => {
    const locked = path.join(dir, "locked");
    fs.mkdirSync(locked, { mode: 0o500 });
    expect(inspectFolder("models", path.join(locked, "Modelos"), INSTALL).issue).toBe("not_writable");
    expect(inspectFolder("models", locked, INSTALL).issue).toBe("not_writable");
  });

  it("rejects a file, another installation's folder, a relative path and a shared folder", () => {
    const file = path.join(dir, "file");
    fs.writeFileSync(file, "");
    expect(inspectFolder("database", file, INSTALL).issue).toBe("not_a_directory");
    const foreign = path.join(dir, "foreign");
    fs.mkdirSync(foreign);
    writeMarker(foreign, { installId: "another", kind: "database" });
    expect(inspectFolder("database", foreign, INSTALL).issue).toBe("foreign");
    expect(inspectFolder("database", "Sauri/Base", INSTALL).issue).toBe("unavailable");
    const same = path.join(dir, "same");
    const issues = inspectFolders({ recordings: same, database: same, models: path.join(dir, "m") }, INSTALL);
    expect(issues.map((info) => info.issue)).toEqual(["duplicate", "duplicate", undefined]);
  });

  it("creates and marks all three folders, and accepts its own marker again", () => {
    const paths = folders();
    expect(prepareFolders(paths, INSTALL)).toEqual([]);
    for (const kind of ["recordings", "database", "models"] as const) {
      expect(readMarker(paths[kind])).toEqual({ installId: INSTALL, kind });
      expect(fs.readdirSync(paths[kind])).toEqual([MARKER_FILE]);
    }
    expect(folderProblems(paths, INSTALL)).toEqual([]);
    expect(prepareFolders(paths, INSTALL)).toEqual([]);
  });

  it("creates nothing when one folder is rejected", () => {
    const paths = folders();
    const locked = path.join(dir, "locked");
    fs.mkdirSync(locked, { mode: 0o500 });
    const result = prepareFolders({ ...paths, models: path.join(locked, "Modelos") }, INSTALL);
    expect(result.find((info) => info.kind === "models")?.issue).toBe("not_writable");
    expect(fs.existsSync(paths.recordings)).toBe(false);
  });
});
