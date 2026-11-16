import { describe, expect, it } from "vitest";
import { readdirSync, readFileSync } from "node:fs";
import { join, relative } from "node:path";
import {
  BACKGROUND_GROUPS,
  compositeOverWhite,
  contrastRatio,
  parseColorTokens,
  parseContrastTable,
  parsePaletteTable,
} from "./contract";

const tokensCss = readFileSync(join(__dirname, "tokens.css"), "utf8");
const designMd = readFileSync(join(__dirname, "../../../DESIGN.md"), "utf8");
const tokens = parseColorTokens(tokensCss);
const palette = parsePaletteTable(designMd);
const contrastRows = parseContrastTable(designMd);

// Source files the design contract governs: no literal colors or web fonts outside tokens.css.
const srcRoot = join(__dirname, "..");
function walk(dir: string): string[] {
  return readdirSync(dir, { withFileTypes: true }).flatMap((entry) =>
    entry.isDirectory() ? walk(join(dir, entry.name)) : [join(dir, entry.name)],
  );
}
const governed = walk(srcRoot)
  .map((path) => relative(srcRoot, path))
  .filter((path) => /\.(css|ts|tsx)$/.test(path))
  .filter((path) => !/\.test\.tsx?$/.test(path) && !/^design\/(tokens\.css|contract\.ts)$/.test(path) && path !== "vite-env.d.ts")
  .map((path) => [path, readFileSync(join(srcRoot, path), "utf8")] as const);

describe("DESIGN.md palette table", () => {
  it("lists exactly the color tokens declared in tokens.css", () => {
    expect(Object.keys(palette).sort()).toEqual(Object.keys(tokens).sort());
  });

  it.each(Object.keys(palette))("%s matches tokens.css in light and dark", (name) => {
    expect(tokens[name]).toEqual(palette[name]);
  });
});

describe("DESIGN.md contrast table", () => {
  it("covers the declared pairs", () => {
    expect(contrastRows.length).toBeGreaterThan(30);
  });

  it.each(contrastRows.map((row) => [`${row.text} / ${row.background}`, row] as const))("%s", (_label, row) => {
    const backgrounds = BACKGROUND_GROUPS[row.background] ?? [row.background];
    const measure = (mode: "light" | "dark") =>
      Math.min(...backgrounds.map((bg) => contrastRatio(tokens[row.text][mode], tokens[bg][mode])));
    const light = measure("light");
    const dark = measure("dark");
    expect(Number(light.toFixed(2))).toBe(row.light);
    expect(Number(dark.toFixed(2))).toBe(row.dark);
    if (row.note.startsWith("exc")) {
      // Documented exception (DESIGN.md 3.3): must stay within 0.1 of the minimum and be dark-safe.
      expect(light).toBeGreaterThanOrEqual(row.min - 0.1);
      expect(dark).toBeGreaterThanOrEqual(row.min);
    } else {
      expect(light).toBeGreaterThanOrEqual(row.min);
      expect(dark).toBeGreaterThanOrEqual(row.min);
    }
  });

  it("keeps on-scrim readable over the strong scrim on a pure white page", () => {
    for (const mode of ["light", "dark"] as const) {
      const over = compositeOverWhite(tokens["scrim-strong"][mode]);
      expect(contrastRatio(tokens["on-scrim"][mode], over)).toBeGreaterThanOrEqual(4.5);
    }
  });
});

describe("token scales", () => {
  const scale = (prefix: string) =>
    [...tokensCss.matchAll(new RegExp(`--ds-${prefix}-(\\w+):\\s*(\\d+)px`, "g"))].map((m) => Number(m[2]));

  it("uses the 4/8/12/16/24/32 spacing scale", () => {
    expect(scale("space")).toEqual([4, 8, 12, 16, 24, 32]);
  });

  it("fixes the touch target, focus ring and icon scale", () => {
    expect(tokensCss).toMatch(/--ds-target:\s*44px/);
    expect(tokensCss).toMatch(/--ds-focus-width:\s*2px/);
    expect(tokensCss).toMatch(/--ds-focus-offset:\s*2px/);
    expect(scale("icon")).toEqual([12, 14, 16, 18]);
  });

  it("supports the system theme and an explicit data-theme override", () => {
    expect(tokensCss).toMatch(/color-scheme:\s*light dark/);
    expect(tokensCss).toMatch(/:root\[data-theme="light"\]\s*{\s*color-scheme:\s*light/);
    expect(tokensCss).toMatch(/:root\[data-theme="dark"\]\s*{\s*color-scheme:\s*dark/);
  });

  it("uses the system font stacks", () => {
    expect(tokensCss).toMatch(/--ds-font-sans:\s*system-ui/);
    expect(tokensCss).toMatch(/--ds-font-mono:\s*ui-monospace/);
  });
});

describe("components use tokens only", () => {
  it("has files to check", () => {
    expect(governed.length).toBeGreaterThan(10);
  });

  it.each(governed)("%s has no literal colors or web fonts", (_path, source) => {
    expect(source).not.toMatch(/#[0-9a-fA-F]{3,8}\b/);
    expect(source).not.toMatch(/\b(?:rgba?|hsla?)\(/);
    expect(source).not.toMatch(/Literata|Nunito|JetBrains|@fontsource/);
    expect(source).not.toMatch(/(?:linear|radial|conic)-gradient|backdrop-filter/);
  });
});
