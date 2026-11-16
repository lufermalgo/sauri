// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createMemoryStorage } from "../test/storage";
import i18n, {
  LANGUAGE_STORAGE_KEY, detectLanguage, initLanguage, matchLanguage, readStoredLanguage, setLanguage, t,
} from "./index";
import { compareText, formatDate, formatList, formatNumber, toUpperLocale } from "./format";

function stubLanguages(languages: string[]) {
  Object.defineProperty(window.navigator, "languages", { value: languages, configurable: true });
  Object.defineProperty(window.navigator, "language", { value: languages[0], configurable: true });
}

beforeEach(() => { vi.stubGlobal("localStorage", createMemoryStorage()); });
afterEach(() => { vi.unstubAllGlobals(); });

describe("matchLanguage", () => {
  it.each([
    ["es", "es"], ["es-CO", "es"], ["ES_mx", "es"], ["en", "en"], ["en-US", "en"], ["EN-gb", "en"],
    ["fr-FR", null], ["pt-BR", null], ["", null], [null, null], [undefined, null],
  ])("maps %s to %s", (tag, expected) => {
    expect(matchLanguage(tag)).toBe(expected);
  });
});

describe("detectLanguage", () => {
  it("prefers the saved language over the browser", () => {
    expect(detectLanguage({ stored: "en", browserLanguages: ["es-CO"] })).toBe("en");
    expect(detectLanguage({ stored: "es", browserLanguages: ["en-US"] })).toBe("es");
  });

  it("ignores a saved value that is not a supported language", () => {
    expect(detectLanguage({ stored: "klingon", browserLanguages: ["en-US"] })).toBe("en");
  });

  it("uses the first supported browser language, in order of preference", () => {
    expect(detectLanguage({ browserLanguages: ["en-GB", "es"] })).toBe("en");
    expect(detectLanguage({ browserLanguages: ["fr-FR", "en-US"] })).toBe("en");
    expect(detectLanguage({ browserLanguages: ["es-MX", "en"] })).toBe("es");
  });

  it("falls back to Spanish for any other language or none", () => {
    expect(detectLanguage({ browserLanguages: ["fr-FR", "de"] })).toBe("es");
    expect(detectLanguage({})).toBe("es");
  });
});

describe("start-up language", () => {
  it("follows the browser when nothing is saved and does not save it", async () => {
    stubLanguages(["en-US"]);
    await initLanguage();
    expect(i18n.language).toBe("en");
    expect(document.documentElement.lang).toBe("en");
    expect(localStorage.getItem(LANGUAGE_STORAGE_KEY)).toBeNull();
  });

  it("uses the saved language over the browser", async () => {
    stubLanguages(["en-US"]);
    localStorage.setItem(LANGUAGE_STORAGE_KEY, "es");
    await initLanguage();
    expect(i18n.language).toBe("es");
    expect(document.documentElement.lang).toBe("es");
  });

  it("starts in Spanish for an unsupported browser language", async () => {
    stubLanguages(["ja-JP"]);
    await initLanguage();
    expect(i18n.language).toBe("es");
  });
});

describe("switching", () => {
  it("translates, updates the document and remembers the choice", async () => {
    expect(t("login:submit")).toBe("Iniciar sesión");
    await setLanguage("en");
    expect(t("login:submit")).toBe("Log in");
    expect(document.documentElement.lang).toBe("en");
    expect(document.title).toBe("Sauri");
    expect(readStoredLanguage()).toBe("en");
    await setLanguage("es");
    expect(t("login:submit")).toBe("Iniciar sesión");
    expect(document.documentElement.lang).toBe("es");
    expect(readStoredLanguage()).toBe("es");
  });

  it("still switches when storage is blocked", async () => {
    const blocked = () => { throw new Error("blocked"); };
    vi.stubGlobal("localStorage", { getItem: blocked, setItem: blocked });
    await setLanguage("en");
    expect(i18n.language).toBe("en");
    expect(readStoredLanguage()).toBeNull();
  });

  it("falls back to Spanish for a namespace English does not have", async () => {
    await setLanguage("en");
    i18n.removeResourceBundle("en", "login");
    expect(t("login:submit")).toBe("Iniciar sesión");
  });
});

describe("plural forms", () => {
  it.each([
    ["es", 0, "0 hablantes"], ["es", 1, "1 hablante"], ["es", 2, "2 hablantes"],
    ["en", 0, "0 speakers"], ["en", 1, "1 speaker"], ["en", 2, "2 speakers"],
  ] as const)("%s with %i", async (language, count, expected) => {
    await setLanguage(language, { persist: false });
    expect(t("library:speakers", { count })).toBe(expected);
  });

  it("uses the other form for round millions, where Spanish has a third plural category", () => {
    expect(new Intl.PluralRules("es").select(1_000_000)).toBe("many");
    expect(t("library:speakers", { count: 1_000_000 })).toBe("1000000 hablantes");
  });

  it("builds composed bulk messages in both languages", async () => {
    expect(t("library:bulk.deleted", { count: 1 })).toBe("Se eliminó 1 grabación.");
    expect(t("library:bulk.deleted", { count: 3 })).toBe("Se eliminaron 3 grabaciones.");
    await setLanguage("en", { persist: false });
    expect(t("library:bulk.deleted", { count: 1 })).toBe("Deleted 1 recording.");
    expect(t("library:bulk.deleted", { count: 3 })).toBe("Deleted 3 recordings.");
    expect(t("library:bulk.skippedNoSummary", { count: 1 })).toBe("1 was skipped because it has no summary yet.");
    expect(t("library:bulk.skippedNoSummary", { count: 2 })).toBe("2 were skipped because they have no summary yet.");
  });

  it("reads a single minute as a phrase in both languages", async () => {
    expect(t("processing:remaining", { count: 1 })).toBe("Falta alrededor de un minuto, estimado");
    expect(t("processing:remaining", { count: 5 })).toBe("Faltan unos 5 min, estimado");
    await setLanguage("en", { persist: false });
    expect(t("processing:remaining", { count: 1 })).toBe("About a minute left, estimated");
    expect(t("processing:remaining", { count: 5 })).toBe("About 5 min left, estimated");
  });
});

describe("Intl formatting follows the language", () => {
  it("formats numbers, dates, lists and sorting", async () => {
    const date = new Date(2026, 10, 16, 15, 7);
    expect(formatNumber(1.5, { minimumFractionDigits: 1 })).toBe("1,5");
    expect(formatDate(date, { day: "numeric", month: "long", year: "numeric" })).toBe("16 de noviembre de 2026");
    expect(formatList(["a", "b", "c"])).toBe("a, b y c");
    expect(compareText("Ñu", "Zorro")).toBeLessThan(0);
    expect(toUpperLocale("ñ")).toBe("Ñ");
    await setLanguage("en", { persist: false });
    expect(formatNumber(1.5, { minimumFractionDigits: 1 })).toBe("1.5");
    expect(formatDate(date, { day: "numeric", month: "long", year: "numeric" })).toBe("November 16, 2026");
    expect(formatList(["a", "b", "c"])).toBe("a, b, and c");
  });
});
