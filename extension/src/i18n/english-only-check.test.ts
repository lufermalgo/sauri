import { execFileSync, spawnSync } from "node:child_process";
import { mkdtempSync, mkdirSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { expect, it } from "vitest";

it("exempts the extension translation files, not identifiers in extension code", () => {
  const root = mkdtempSync(join(tmpdir(), "sauri-language-"));
  const script = resolve("../scripts/dev/check_english_only.py");
  const accentedWord = `Grabaci${String.fromCodePoint(243)}n`;
  try {
    const translations = join(root, "extension/src/locales/es/panel.json");
    mkdirSync(dirname(translations), { recursive: true });
    writeFileSync(translations, JSON.stringify({ heading: accentedWord }));
    expect(() => execFileSync("python3", [script, translations])).not.toThrow();
    for (const surface of ["panel", "options"]) {
      const code = join(root, `extension/src/${surface}/Invalid.ts`);
      mkdirSync(dirname(code), { recursive: true });
      writeFileSync(code, `const ${accentedWord.toLowerCase()} = 1;`);
      const result = spawnSync("python3", [script, code], { encoding: "utf8" });
      expect(result.status).toBe(1);
      expect(result.stdout).toContain(accentedWord.toLowerCase());
    }
  } finally { rmSync(root, { recursive: true }); }
});
