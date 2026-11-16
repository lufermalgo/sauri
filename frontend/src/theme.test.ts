// @vitest-environment jsdom
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  THEME_STORAGE_KEY,
  applyTheme,
  initTheme,
  readAppliedTheme,
  readStoredTheme,
  setTheme,
} from "./theme";

function createLocalStorage(): Storage {
  const values = new Map<string, string>();
  return {
    get length() { return values.size; },
    clear: () => values.clear(),
    getItem: (key) => values.get(key) ?? null,
    key: (index) => [...values.keys()][index] ?? null,
    removeItem: (key) => values.delete(key),
    setItem: (key, value) => values.set(key, String(value)),
  };
}

beforeEach(() => {
  vi.stubGlobal("localStorage", createLocalStorage());
});

afterEach(() => {
  vi.unstubAllGlobals();
  document.documentElement.removeAttribute("data-theme");
});

describe("theme", () => {
  it("defaults to the system theme when nothing valid is stored", () => {
    expect(readStoredTheme()).toBe("system");
    localStorage.setItem(THEME_STORAGE_KEY, "sepia");
    expect(readStoredTheme()).toBe("system");
    initTheme();
    expect(document.documentElement.hasAttribute("data-theme")).toBe(false);
  });

  it("forces light or dark through data-theme and clears it for system", () => {
    applyTheme("dark");
    expect(readAppliedTheme()).toBe("dark");
    applyTheme("light");
    expect(document.documentElement.getAttribute("data-theme")).toBe("light");
    applyTheme("system");
    expect(readAppliedTheme()).toBe("system");
  });

  it("stores the choice and re-applies it at start", () => {
    setTheme("dark");
    expect(localStorage.getItem(THEME_STORAGE_KEY)).toBe("dark");
    document.documentElement.removeAttribute("data-theme");
    initTheme();
    expect(readAppliedTheme()).toBe("dark");
  });

  it("does not throw when storage is blocked", () => {
    const fail = () => { throw new DOMException("blocked", "SecurityError"); };
    vi.stubGlobal("localStorage", { getItem: fail, setItem: fail, removeItem: fail });
    expect(readStoredTheme()).toBe("system");
    expect(() => setTheme("light")).not.toThrow();
    expect(readAppliedTheme()).toBe("light");
  });

  it("is applied before first paint by the inline script in index.html, with the same key", () => {
    const html = readFileSync(join(__dirname, "../index.html"), "utf8");
    const script = /<script>([\s\S]*?)<\/script>/.exec(html)?.[1];
    expect(script).toBeTruthy();
    expect(script).toContain(`"${THEME_STORAGE_KEY}"`);
    // The inline script is classic and blocking, so it must precede the module entry.
    expect(html.indexOf("<script>")).toBeLessThan(html.indexOf('type="module"'));

    localStorage.setItem(THEME_STORAGE_KEY, "dark");
    new Function(script!)();
    expect(readAppliedTheme()).toBe("dark");

    document.documentElement.removeAttribute("data-theme");
    localStorage.setItem(THEME_STORAGE_KEY, "system");
    new Function(script!)();
    expect(readAppliedTheme()).toBe("system");
  });
});
