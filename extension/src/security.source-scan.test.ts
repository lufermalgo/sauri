// Source-level guards for the session credentials (security hardening). These fail when a change
// puts a token into synced storage, logs it, puts it in a URL, or exposes it to pages. The access token
// lives in chrome.storage.session; the refresh token is the only thing allowed in chrome.storage.local.
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
const REFRESH_MODULE = "src/core/api/session-refresh.ts";
const FETCH_MODULE = "src/core/api/authorized-fetch.ts";
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
      .filter((source) => source.file !== TOKEN_MODULE && /["'](authToken|sauriSessionToken|sauriRefreshToken)["']/.test(source.text))
      .map((source) => source.file);
    expect(offenders).toEqual([]);
  });

  it("only ever removes the legacy key from the synced and local areas (never reads or writes it)", () => {
    const module = sources.find((source) => source.file === TOKEN_MODULE)!.text;
    expect(module).not.toMatch(/storage\[area\]\s*\.\s*(get|set)\b/);
    expect(module).not.toMatch(/localStorage|sessionStorage|indexedDB/);
    // The only legacy-area call is the removal loop.
    expect([...module.matchAll(/storage\[area\]\.(\w+)/g)].map((match) => match[1])).toEqual(["remove"]);
  });
});

describe("the refresh token is the only credential on disk, and only in chrome.storage.local", () => {
  it("is read and written through session-token.ts alone, always under its own key", () => {
    const module = sources.find((source) => source.file === TOKEN_MODULE)!.text;
    const localCalls = [...module.matchAll(/storage\.local\s*\.\s*(\w+)\(([^)]*)\)/g)];
    expect(localCalls.length).toBeGreaterThan(0);
    for (const call of localCalls) expect(call[2], call[0]).toMatch(/REFRESH_KEY/);
  });

  it("is never kept in session storage", () => {
    const module = sources.find((source) => source.file === TOKEN_MODULE)!.text;
    for (const call of module.matchAll(/storage\.session\s*\.\s*(\w+)\(([^)]*)\)/g)) expect(call[2], call[0]).not.toMatch(/REFRESH_KEY|refresh/i);
  });

  it("is handled only by the session modules and the sign-in call", () => {
    const users = sources.filter((source) => /refresh_?token|RefreshToken/i.test(source.text)).map((source) => source.file).sort();
    expect(users).toEqual(["src/core/api/client.ts", REFRESH_MODULE, TOKEN_MODULE].sort());
  });

  it("is never put in a runtime or window message", () => {
    const offenders = sources.filter((source) =>
      [...source.text.matchAll(/(?:sendMessage|postMessage)\(([^;]*?)\);/g)].some((call) => /refresh|token/i.test(expressionsOnly(call[1])))).map((source) => source.file);
    expect(offenders).toEqual([]);
  });

  it("is only sent to the refresh and revoke endpoints of the backend", () => {
    const sendsToken = sources.filter((source) => /JSON\.stringify\(\{\s*refresh_token/.test(source.text)).map((source) => source.file);
    expect(sendsToken).toEqual([REFRESH_MODULE]);
    const module = sources.find((source) => source.file === REFRESH_MODULE)!.text;
    expect([...module.matchAll(/fetch\(`\$\{backendUrl\}([^`]*)`/g)].map((match) => match[1]).sort())
      .toEqual(["/api/v1/auth/refresh", "/api/v1/auth/refresh/revoke"]);
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

  it("is only attached as an Authorization header by the shared authorized fetch", () => {
    const users = sources.filter((source) => /Bearer\s*\$\{/.test(source.text)).map((source) => source.file).sort();
    expect(users).toEqual([FETCH_MODULE]);
  });

  it("is unreachable for content scripts and the injected overlay", () => {
    const pageFacing = sources.filter((source) => source.file === "src/content.ts" || source.file.startsWith("src/overlay/") || source.file === "src/overlay-injection.ts");
    expect(pageFacing.length).toBeGreaterThan(3);
    const offenders = pageFacing.filter((source) => /session-token|core\/api|chrome\.storage|authToken|sauriSessionToken|sauriRefreshToken|refresh_token|Authorization/.test(source.text) && source.file !== "src/overlay-injection.ts")
      .map((source) => source.file);
    expect(offenders).toEqual([]);
  });

  it("is not exposed through web_accessible_resources", () => {
    expect(JSON.stringify(manifest.web_accessible_resources ?? [])).not.toMatch(/token|session|detail/i);
    expect(manifest.web_accessible_resources).toBeUndefined();
  });
});
