// Pure helpers that check tokens.css against the tables in DESIGN.md (palette and contrast).
// Mirrored in frontend/src/design/contract.ts; keep both in sync.

export type ThemePair = { light: string; dark: string };

/** Groups of backgrounds that a contrast row in DESIGN.md refers to. */
export const BACKGROUND_GROUPS: Record<string, string[]> = {
  surfaces: ["bg", "surface", "surface-raised", "sidebar", "fill", "fill-hover", "fill-strong"],
  page: ["bg", "surface", "surface-raised", "sidebar"],
  reading: ["bg", "surface"],
  base: ["bg", "surface", "surface-raised", "fill"],
};

/** Splits "a, b" at the first comma that is not inside parentheses. */
function splitTopLevel(text: string): [string, string] {
  let depth = 0;
  for (let i = 0; i < text.length; i += 1) {
    const char = text[i];
    if (char === "(") depth += 1;
    else if (char === ")") depth -= 1;
    else if (char === "," && depth === 0) return [text.slice(0, i).trim(), text.slice(i + 1).trim()];
  }
  throw new Error(`light-dark() needs two arguments: ${text}`);
}

/** Reads every color token (`--ds-x: light-dark(a, b)` or a single hex) from a token stylesheet. */
export function parseColorTokens(css: string): Record<string, ThemePair> {
  const tokens: Record<string, ThemePair> = {};
  const pattern = /--ds-([a-z0-9-]+):\s*(?:light-dark\(((?:[^;]|\n)*?)\)|(#[0-9a-fA-F]{6}));/g;
  for (const match of css.matchAll(pattern)) {
    const [, name, pair, single] = match;
    if (single) tokens[name] = { light: single, dark: single };
    else {
      const [light, dark] = splitTopLevel(pair);
      tokens[name] = { light, dark };
    }
  }
  return tokens;
}

/** Palette rows `| \`name\` | \`light\` | \`dark\` | ... |` between the palette markers. */
export function parsePaletteTable(markdown: string): Record<string, ThemePair> {
  const block = markdown.split("<!-- palette:start -->")[1]?.split("<!-- palette:end -->")[0] ?? "";
  const rows: Record<string, ThemePair> = {};
  for (const match of block.matchAll(/^\|\s*`([a-z0-9-]+)`\s*\|\s*`([^`]+)`\s*\|\s*`([^`]+)`\s*\|/gm)) {
    rows[match[1]] = { light: match[2], dark: match[3] };
  }
  return rows;
}

export type ContrastRow = { text: string; background: string; min: number; light: number; dark: number; note: string };

/** Contrast rows between the contrast markers. */
export function parseContrastTable(markdown: string): ContrastRow[] {
  const block = markdown.split("<!-- contrast:start -->")[1]?.split("<!-- contrast:end -->")[0] ?? "";
  const pattern = /^\|\s*`([a-z0-9-]+)`\s*\/\s*`([a-z0-9-]+)`\s*\|\s*([\d.]+)\s*\|\s*([\d.]+)\s*\|\s*([\d.]+)\s*\|([^|]*)\|/gm;
  return [...block.matchAll(pattern)].map((m) => ({
    text: m[1],
    background: m[2],
    min: Number(m[3]),
    light: Number(m[4]),
    dark: Number(m[5]),
    note: m[6].trim(),
  }));
}

function channel(value: number): number {
  const c = value / 255;
  return c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
}

function parseHex(hex: string): [number, number, number] {
  if (!/^#[0-9a-fA-F]{6}$/.test(hex)) throw new Error(`Expected #rrggbb, got "${hex}"`);
  return [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16)) as [number, number, number];
}

function luminance(hex: string): number {
  const [r, g, b] = parseHex(hex);
  return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b);
}

/** WCAG 2.x contrast ratio between two solid #rrggbb colors. */
export function contrastRatio(a: string, b: string): number {
  const [x, y] = [luminance(a), luminance(b)];
  return (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05);
}

/** Resolves `rgb(r g b / a)` over pure white and returns the opaque #rrggbb. */
export function compositeOverWhite(color: string): string {
  const match = color.match(/^rgb\(\s*(\d+)\s+(\d+)\s+(\d+)\s*\/\s*([\d.]+)\s*\)$/);
  if (!match) throw new Error(`Expected rgb(r g b / a), got "${color}"`);
  const alpha = Number(match[4]);
  const hex = [match[1], match[2], match[3]]
    .map((v) => Math.round(Number(v) * alpha + 255 * (1 - alpha)).toString(16).padStart(2, "0"))
    .join("");
  return `#${hex}`;
}
