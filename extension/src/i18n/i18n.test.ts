import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  checkSourcePlurals, compareNamespace, findHardcodedSpanish, isExemptFromSpanishCheck, type Resource,
} from "../../../frontend/src/i18n/check";
import i18n, {
  LANGUAGE_STORAGE_KEY, detectLanguage, initLanguage, matchLanguage, readStoredLanguage, setLanguage, t, watchLanguage,
} from "./index";

const localesDir = join(import.meta.dirname, "..", "locales");

function read(language: string): Record<string, Resource> {
  const dir = join(localesDir, language);
  return Object.fromEntries(readdirSync(dir).filter((file) => file.endsWith(".json"))
    .map((file) => [file.slice(0, -5), JSON.parse(readFileSync(join(dir, file), "utf8")) as Resource]));
}

function sources(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    return statSync(path).isDirectory() ? sources(path) : /\.tsx?$/.test(name) ? [path] : [];
  });
}

/** A `chrome.storage.local` + `chrome.i18n` stand-in with a working `onChanged`. */
function stubChrome({ stored, uiLanguage = "es" }: { stored?: string; uiLanguage?: string }) {
  const values: Record<string, unknown> = stored ? { [LANGUAGE_STORAGE_KEY]: stored } : {};
  const listeners: Array<(changes: Record<string, chrome.storage.StorageChange>, area: string) => void> = [];
  vi.stubGlobal("chrome", {
    i18n: { getUILanguage: () => uiLanguage },
    storage: {
      local: {
        get: vi.fn(async (key: string) => (key in values ? { [key]: values[key] } : {})),
        set: vi.fn(async (entries: Record<string, unknown>) => { Object.assign(values, entries); }),
      },
      onChanged: { addListener: (fn: never) => listeners.push(fn), removeListener: vi.fn() },
    },
  });
  return { values, emit: (changes: Record<string, chrome.storage.StorageChange>, area = "local") => listeners.forEach((fn) => fn(changes, area)) };
}

afterEach(() => { vi.unstubAllGlobals(); });

describe("the real translation files", () => {
  const es = read("es");
  const en = read("en");

  it("have English for every Spanish namespace and key, with the same variables", () => {
    expect(Object.keys(en).sort()).toEqual(Object.keys(es).sort());
    expect(Object.keys(es).flatMap((namespace) => compareNamespace(namespace, es[namespace], en[namespace], "en"))).toEqual([]);
  });

  it("carry complete plural forms in Spanish", () => {
    expect(Object.keys(es).flatMap((namespace) => checkSourcePlurals(namespace, es[namespace]))).toEqual([]);
  });

  it("leave no Spanish text in components or helpers", () => {
    const found = sources(join(import.meta.dirname, "..")).filter((file) => !isExemptFromSpanishCheck(file))
      .flatMap((file) => findHardcodedSpanish(readFileSync(file, "utf8"), file).map((finding) => `${file}:${finding.line} ${finding.text}`));
    expect(found).toEqual([]);
  });
});

describe("the manifest messages", () => {
  it("exist in both languages", () => {
    const messages = (language: string) => JSON.parse(readFileSync(join(import.meta.dirname, "..", "..", "public", "_locales", language, "messages.json"), "utf8"));
    expect(Object.keys(messages("en")).sort()).toEqual(Object.keys(messages("es")).sort());
  });
});

describe("matchLanguage", () => {
  it.each([
    ["es", "es"], ["es-419", "es"], ["ES_mx", "es"], ["en", "en"], ["en-US", "en"], ["EN-gb", "en"],
    ["fr-FR", null], ["pt-BR", null], ["", null], [null, null], [undefined, null],
  ])("maps %s to %s", (tag, expected) => {
    expect(matchLanguage(tag)).toBe(expected);
  });
});

describe("detectLanguage", () => {
  it("prefers the saved language over the browser", () => {
    expect(detectLanguage({ stored: "en", browserLanguage: "es-CO" })).toBe("en");
    expect(detectLanguage({ stored: "es", browserLanguage: "en-US" })).toBe("es");
  });

  it("ignores a saved value that is not a supported language", () => {
    expect(detectLanguage({ stored: "klingon", browserLanguage: "en-US" })).toBe("en");
  });

  it("follows the browser when nothing is saved, and falls back to Spanish otherwise", () => {
    expect(detectLanguage({ browserLanguage: "en-GB" })).toBe("en");
    expect(detectLanguage({ browserLanguage: "es-MX" })).toBe("es");
    expect(detectLanguage({ browserLanguage: "fr-FR" })).toBe("es");
    expect(detectLanguage({})).toBe("es");
  });
});

describe("start-up language", () => {
  it("follows the browser interface language when nothing is saved, without saving it", async () => {
    const chromeStub = stubChrome({ uiLanguage: "en-US" });
    await initLanguage();
    expect(i18n.language).toBe("en");
    expect(document.documentElement.lang).toBe("en");
    expect(t("panel:panelTitle")).toBe("Record meeting");
    expect(chromeStub.values[LANGUAGE_STORAGE_KEY]).toBeUndefined();
  });

  it("uses the saved language over the browser's", async () => {
    stubChrome({ stored: "es", uiLanguage: "en-US" });
    await initLanguage();
    expect(i18n.language).toBe("es");
    expect(t("panel:panelTitle")).toBe("Grabar reunión");
  });

  it("falls back to the browser language when the storage cannot be read", async () => {
    stubChrome({ uiLanguage: "en" });
    (chrome.storage.local.get as ReturnType<typeof vi.fn>).mockRejectedValue(new Error("blocked"));
    expect(await readStoredLanguage()).toBeNull();
    await initLanguage();
    expect(i18n.language).toBe("en");
  });

  it("remembers a choice made in the options page", async () => {
    const chromeStub = stubChrome({});
    await setLanguage("en");
    expect(chromeStub.values[LANGUAGE_STORAGE_KEY]).toBe("en");
    expect(i18n.language).toBe("en");
  });

  it("switches when another extension page saves a language, and ignores other changes", async () => {
    const chromeStub = stubChrome({});
    watchLanguage();
    chromeStub.emit({ [LANGUAGE_STORAGE_KEY]: { newValue: "en" } });
    await vi.waitFor(() => expect(i18n.language).toBe("en"));
    chromeStub.emit({ [LANGUAGE_STORAGE_KEY]: { newValue: "es" } }, "sync");
    chromeStub.emit({ somethingElse: { newValue: "es" } });
    chromeStub.emit({ [LANGUAGE_STORAGE_KEY]: { newValue: "klingon" } });
    await Promise.resolve();
    expect(i18n.language).toBe("en");
  });
});

describe("translated texts", () => {
  it("fill variables in both languages", async () => {
    expect(t("panel:countdownSeconds", { seconds: 5 })).toBe("5 s");
    await setLanguage("en", { persist: false });
    expect(t("permission:grantedDevice", { device: "USB" })).toBe("You can now record with your voice. We chose “USB”; you can change it in the panel.");
    expect(t("overlay:notice")).toBe("This meeting is being recorded with Sauri.");
  });
});
