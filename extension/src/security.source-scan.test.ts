// Source-level guards for the session token (security hardening). These fail when a change
// puts the token back into synced storage, logs it, puts it in a URL, or exposes it to pages.
import { describe, expect, it } from "vitest";
import fs from "fs";
import path from "path";

const root = path.resolve(__dirname, "..");
const srcDir = path.join(root, "src");

function walk(dir: string): string[] {
  return fs.readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) return walk(full);
    return /\.(ts|tsx)$/.test(entry.name) && !/\.test\.(ts|tsx)$/.test(entry.name) && !full.includes(`${path.sep}e2e${path.sep}`) ? [full] : [];
  });
}

/** Source without comments, so prose that mentions an API cannot trip or hide a check. */
function stripComments(text: string): string {
  return text.replace(/\/\*[\s\S]*?\*\//g, "").replace(/(^|\s)\/\/.*$/gm, "$1");
}

/** Keeps only what is evaluated: static string text is removed, `${...}` expressions stay. */
function expressionsOnly(text: string): string {
  return text
    .replace(/`([^`]*)`/g, (_match, body: string) => [...body.matchAll(/\$\{([^}]*)\}/g)].map((m) => m[1]).join(" "))
    .replace(/"[^"\n]*"|'[^'\n]*'/g, '""');
}

const sources = walk(srcDir).map((file) => ({ file: path.relative(root, file), text: stripComments(fs.readFileSync(file, "utf-8")) }));
const TOKEN_MODULE = "src/core/session-token.ts";
const manifest = JSON.parse(fs.readFileSync(path.join(root, "manifest.json"), "utf-8"));

describe("the session token never reaches synced storage", () => {
  it("finds the source files", () => {
    expect(sources.length).toBeGreaterThan(20);
    expect(sources.some((source) => source.file === TOKEN_MODULE)).toBe(true);
  });

  it("uses chrome.storage.sync nowhere in the extension", () => {
    const offenders = sources.filter((source) => /storage\.sync\b|storage\[\s*["']sync["']\s*\]/.test(source.text)).map((source) => source.file);
    expect(offenders).toEqual([]);
  });

  it("touches storage areas for the token only through session-token.ts", () => {
    const offenders = sources
      .filter((source) => source.file !== TOKEN_MODULE && /["'](authToken|sauriSessionToken)["']/.test(source.text))
      .map((source) => source.file);
    expect(offenders).toEqual([]);
  });

  it("only ever removes the legacy key from the synced and local areas (never reads or writes it)", () => {
    const module = sources.find((source) => source.file === TOKEN_MODULE)!.text;
    expect(module).not.toMatch(/storage\.(local|sync)\s*\.\s*(get|set)\b/);
    expect(module).not.toMatch(/storage\[area\]\s*\.\s*(get|set)\b/);
    expect(module).not.toMatch(/localStorage|sessionStorage|indexedDB/);
    // The only legacy-area call is the removal loop.
    expect([...module.matchAll(/storage\[area\]\.(\w+)/g)].map((match) => match[1])).toEqual(["remove"]);
  });
});

describe("the session token is never leaked", () => {
  it("is never logged", () => {
    const offenders = sources.filter((source) =>
      [...source.text.matchAll(/console\.\w+\(([^;]*?)\);/g)].some((call) => /token|authorization|bearer|password/i.test(expressionsOnly(call[1])))).map((source) => source.file);
    expect(offenders).toEqual([]);
  });

  it("is never put in a URL", () => {
    const offenders = sources.filter((source) =>
      /`[^`]*(https?:|\/api\/|\?)[^`]*\$\{[^}]*token[^}]*\}[^`]*`/i.test(source.text)
      || /searchParams\.(set|append)\([^)]*token/i.test(source.text)).map((source) => source.file);
    expect(offenders).toEqual([]);
  });

  it("is only attached as an Authorization header by the API client and the service worker", () => {
    const users = sources.filter((source) => /Bearer\s*\$\{/.test(source.text)).map((source) => source.file).sort();
    expect(users).toEqual(["src/background.ts", "src/core/api/client.ts"]);
  });

  it("is unreachable for content scripts and the injected overlay", () => {
    const pageFacing = sources.filter((source) => source.file === "src/content.ts" || source.file.startsWith("src/overlay/") || source.file === "src/overlay-injection.ts");
    expect(pageFacing.length).toBeGreaterThan(3);
    const offenders = pageFacing.filter((source) => /session-token|core\/api|chrome\.storage|authToken|sauriSessionToken|Authorization/.test(source.text) && source.file !== "src/overlay-injection.ts")
      .map((source) => source.file);
    expect(offenders).toEqual([]);
  });

  it("is not exposed through web_accessible_resources", () => {
    expect(JSON.stringify(manifest.web_accessible_resources ?? [])).not.toMatch(/token|session|detail/i);
    expect(manifest.web_accessible_resources).toBeUndefined();
  });
});
