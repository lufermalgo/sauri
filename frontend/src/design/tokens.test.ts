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
const uiCss = readFileSync(join(__dirname, "../components/ui/ui.css"), "utf8");
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
// The isotype keeps its two fixed brand greens in every theme (brand/README.md); they are not theme tokens.
const BRAND_ASSET_FILES = ["components/ui/BrandMark.tsx"];
const governed = walk(srcRoot)
  .map((path) => relative(srcRoot, path))
  .filter((path) => /\.(css|ts|tsx)$/.test(path))
  .filter((path) => !/\.test\.tsx?$/.test(path) && !/^design\/(tokens\.css|contract\.ts)$/.test(path) && path !== "vite-env.d.ts" && !BRAND_ASSET_FILES.includes(path))
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

  it("fixes the focus ring and icon scale", () => {
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

describe("desktop density scale (DESIGN.md, Densidad de escritorio)", () => {
  const declared = (name: string, css = tokensCss) => css.match(new RegExp(`--ds-${name}:\\s*([^;]+);`))?.[1];
  const [desktopRoot, coarseBlock] = (() => {
    const at = tokensCss.indexOf("@media (pointer: coarse)");
    return [tokensCss.slice(0, at), tokensCss.slice(at)];
  })();

  it("sets the type scale: 14px body, 13 secondary, 12 meta, 11 micro, 15/16 titles", () => {
    expect(declared("text-base", desktopRoot)).toBe("14px");
    expect(declared("text-md", desktopRoot)).toBe("14px");
    expect(declared("text-sm", desktopRoot)).toBe("13px");
    expect(declared("text-xs", desktopRoot)).toBe("12px");
    expect(declared("text-2xs", desktopRoot)).toBe("11px");
    expect(declared("text-lg", desktopRoot)).toBe("15px");
    expect(declared("text-xl", desktopRoot)).toBe("16px");
    expect(declared("leading", desktopRoot)).toBe("1.45");
    expect(declared("leading-relaxed", desktopRoot)).toBe("1.55");
  });

  it("has no 24px or 30px text step for app screens (login keeps the 20px step)", () => {
    expect(tokensCss).not.toMatch(/--ds-text-3xl/);
    const sizes = [...desktopRoot.matchAll(/--ds-text-[\w]+:\s*(\d+)px/g)].map((m) => Number(m[1]));
    expect(Math.max(...sizes)).toBe(20);
  });

  it("sizes controls for a desktop pointer: buttons 28/32/36, icon buttons 30/32, inputs 32", () => {
    expect(declared("control-h-sm", desktopRoot)).toBe("28px");
    expect(declared("control-h-md", desktopRoot)).toBe("32px");
    expect(declared("control-h-lg", desktopRoot)).toBe("36px");
    expect(declared("icon-button-sm", desktopRoot)).toBe("30px");
    expect(declared("icon-button-md", desktopRoot)).toBe("32px");
    expect(declared("target", desktopRoot)).toBe("32px");
    expect(declared("nav-row-h", desktopRoot)).toBe("32px");
    expect(uiCss).toMatch(/\.ui-input\s*{[^}]*min-height:\s*var\(--ds-control-h-md\)/);
    expect(uiCss).toMatch(/\.ui-button--sm\s*{[^}]*min-height:\s*var\(--ds-control-h-sm\)/);
    expect(uiCss).toMatch(/\.ui-button--lg\s*{[^}]*min-height:\s*var\(--ds-control-h-lg\)/);
    expect(uiCss).toMatch(/\.ui-icon-button\s*{[^}]*width:\s*var\(--ds-icon-button-sm\)/);
  });

  it("raises every control to the 44px target only under a coarse pointer", () => {
    expect(coarseBlock).toMatch(/^@media \(pointer: coarse\)/);
    for (const name of ["control-h-sm", "control-h-md", "control-h-lg", "icon-button-sm", "icon-button-md", "nav-row-h", "target"]) {
      expect(declared(name, coarseBlock), name).toBe("44px");
    }
    // Nothing outside that block asks for 44px.
    expect(desktopRoot).not.toMatch(/44px/);
  });

  it("fixes the pane geometry: 48px header strip, 220px side panel, 60px rail, 340px list, 380px notes", () => {
    expect(declared("header-h", desktopRoot)).toBe("48px");
    expect(declared("sidebar-w", desktopRoot)).toBe("220px");
    expect(declared("rail-w", desktopRoot)).toBe("60px");
    expect(declared("list-w", desktopRoot)).toBe("340px");
    expect(declared("side-w", desktopRoot)).toBe("380px");
  });

  it("keeps the radius split: 8px controls, 10px cards, 12px popovers and dialogs", () => {
    expect(declared("radius-sm", desktopRoot)).toBe("8px");
    expect(declared("radius-card", desktopRoot)).toBe("10px");
    expect(declared("radius-md", desktopRoot)).toBe("12px");
    expect(uiCss).toMatch(/\.ui-pane\s*{(?:(?!radius)[^}])*}/);
  });

  it("documents the same scale in DESIGN.md", () => {
    expect(designMd).toMatch(/## 5b\. Densidad de escritorio|Densidad de escritorio/);
    for (const value of ["14px", "28", "32", "36", "340px", "220px", "48px"]) expect(designMd).toContain(value);
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
