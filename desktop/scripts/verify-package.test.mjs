import { createHash } from "node:crypto";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { runtimeProblems } from "./verify-package.mjs";

let dir;
const sha = (text) => createHash("sha256").update(text).digest("hex");

function write(root, rel, text) {
  fs.mkdirSync(path.dirname(path.join(root, rel)), { recursive: true });
  fs.writeFileSync(path.join(root, rel), text);
}

function runtime(root) {
  write(root, "bin/whisper-cli", "whisper build");
  write(root, "python/lib/module.so", "extension");
  write(root, "runtime-manifest.json", JSON.stringify({ artifacts: [{ name: "whisper.cpp", binaries: { "whisper-cli": { sha256: sha("whisper build") } } }] }));
}

beforeEach(() => {
  dir = fs.mkdtempSync(path.join(os.tmpdir(), "sauri-verify-"));
  runtime(path.join(dir, "source"));
  runtime(path.join(dir, "packaged"));
});

afterEach(() => fs.rmSync(dir, { recursive: true, force: true }));

describe("packaged runtime check", () => {
  it("accepts a runtime copied unchanged", () => {
    expect(runtimeProblems(path.join(dir, "packaged"), path.join(dir, "source"))).toEqual([]);
  });

  it("rejects stray bytecode outside the components, even when the staged runtime had it", () => {
    for (const root of ["source", "packaged"]) {
      write(path.join(dir, root), "python/lib/python3.11/re/__pycache__/_parser.cpython-311.pyc", "bytecode");
      write(path.join(dir, root), "python/lib/python3.11/stray.pyc", "bytecode");
      write(path.join(dir, root), "components/core/sqlalchemy/__pycache__/sql.cpython-311.pyc", "pinned bytecode");
    }
    expect(runtimeProblems(path.join(dir, "packaged"), path.join(dir, "source"))).toEqual([
      "python/lib/python3.11/re/__pycache__/_parser.cpython-311.pyc is stray Python bytecode",
      "python/lib/python3.11/stray.pyc is stray Python bytecode",
    ]);
  });

  it("names a re-signed binary and a changed library", () => {
    write(path.join(dir, "packaged"), "bin/whisper-cli", "whisper build, signed again");
    write(path.join(dir, "packaged"), "python/lib/module.so", "extension, signed again");
    expect(runtimeProblems(path.join(dir, "packaged"), path.join(dir, "source"))).toEqual([
      "bin/whisper-cli differs from its pin",
      "bin/whisper-cli differs from the staged runtime",
      "python/lib/module.so differs from the staged runtime",
    ]);
  });
});
