// Guards for local pairing: credentials must not reach sync, logs, URLs, messages, or pages.
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
const TOKEN_MODULE = "src/core/local-pairing.ts";
const FETCH_MODULE = "src/core/api/authorized-fetch.ts";
const manifest = JSON.parse(fs.readFileSync(path.join(root, "manifest.json"), "utf-8"));

describe("local credential storage and retired login", () => {
  it("confines local and legacy credential keys to the pairing module", () => {
    expect(sources.some(source => source.file === TOKEN_MODULE)).toBe(true);
    expect(sources.filter(source => source.file !== TOKEN_MODULE && /["'](authToken|sauriSessionToken|sauriRefreshToken|sauriSignInRequired|sauriLocalToken)["']/.test(source.text)).map(source => source.file)).toEqual([]);
  });
  it("never reads or writes synced storage", () => {
    expect(sources.filter(source => /storage\.sync\.(get|set)|storage\[area\]\.(get|set)/.test(source.text))).toEqual([]);
  });
  it("restricts local storage to trusted extension contexts before reading the token", () => {
    const module = sources.find(source => source.file === TOKEN_MODULE)!.text;
    expect(module.indexOf('setAccessLevel({ accessLevel: "TRUSTED_CONTEXTS" })')).toBeLessThan(module.indexOf("storage.local.get(TOKEN_KEY)"));
    expect(module).not.toMatch(/storage\.session\.(get|set)|localStorage|sessionStorage|indexedDB/);
  });
  it("has no login or refresh endpoints", () => {
    expect(sources.filter(source => /\/auth\/(login|refresh)|refresh_token/.test(source.text))).toEqual([]);
  });
});

describe("the local token is never leaked", () => {
  it("is never put in a runtime or window message", () => {
    const offenders = sources.filter(source =>
      [...source.text.matchAll(/(?:sendMessage|postMessage)\(([^;]*?)\);/g)].some(call => /token|authorization|bearer/i.test(expressionsOnly(call[1])))).map(source => source.file);
    expect(offenders).toEqual([]);
  });

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

  it("is only attached as an Authorization header by the shared authorized fetch", () => {
    const users = sources.filter((source) => /Bearer\s*\$\{/.test(source.text)).map((source) => source.file).sort();
    expect(users).toEqual([FETCH_MODULE]);
  });

  it("is unreachable for content scripts and the injected overlay", () => {
    const pageFacing = sources.filter((source) => source.file === "src/content.ts" || source.file.startsWith("src/overlay/") || source.file === "src/overlay-injection.ts");
    expect(pageFacing.length).toBeGreaterThan(3);
    const offenders = pageFacing.filter((source) => /local-pairing|session-token|core\/api|chrome\.storage|authToken|sauriLocalToken|sauriSessionToken|sauriRefreshToken|refresh_token|Authorization/.test(source.text) && source.file !== "src/overlay-injection.ts")
      .map((source) => source.file);
    expect(offenders).toEqual([]);
  });

  it("is not exposed through web_accessible_resources", () => {
    expect(JSON.stringify(manifest.web_accessible_resources ?? [])).not.toMatch(/token|session|detail/i);
    expect(manifest.web_accessible_resources).toBeUndefined();
  });
});
