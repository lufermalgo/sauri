import { execFileSync, spawnSync } from "node:child_process";
import { mkdtempSync, mkdirSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { expect, it } from "vitest";

it("exempts localized extension copy, not identifiers in extension code", () => {
  const root = mkdtempSync(join(tmpdir(), "sauri-language-"));
  const script = resolve("../scripts/dev/check_english_only.py");
  const accentedWord = `Grabaci${String.fromCodePoint(243)}n`;
  try {
    for (const surface of ["panel", "options"]) {
      const copy = join(root, `extension/src/${surface}/copy/index.ts`);
      mkdirSync(dirname(copy), { recursive: true });
      writeFileSync(copy, `export const copy = { heading: "${accentedWord}" };`);
      expect(() => execFileSync("python3", [script, copy])).not.toThrow();
      const code = join(root, `extension/src/${surface}/Invalid.ts`);
      writeFileSync(code, `const ${accentedWord.toLowerCase()} = 1;`);
      const result = spawnSync("python3", [script, code], { encoding: "utf8" });
      expect(result.status).toBe(1);
      expect(result.stdout).toContain(accentedWord.toLowerCase());
    }
  } finally { rmSync(root, { recursive: true }); }
});
