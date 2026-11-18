import i18n, { type TFunction } from "i18next";
import { initReactI18next, useTranslation } from "react-i18next";
import { es, type Resources } from "../locales/es";
import { desktopBridge } from "../desktop-bridge";
import { DEFAULT_LANGUAGE, detectInitialLanguage, storeLanguage, type Language } from "./languages";

export * from "./languages";

type Tree = { [key: string]: string | Tree };

/**
 * Spanish also has a "many" plural category (round millions: "1 millón de …"), which i18next looks up
 * as `key_many`. The files only carry `_one` and `_other`, so a missing `_many` reuses `_other`
 * instead of showing the raw key.
 */
export function withManyForms(tree: Tree, language: string): Tree {
  const hasMany = new Intl.PluralRules(language).resolvedOptions().pluralCategories.includes("many");
  const out: Tree = {};
  for (const [key, value] of Object.entries(tree)) {
    out[key] = typeof value === "string" ? value : withManyForms(value, language);
    if (hasMany && typeof value === "string" && key.endsWith("_other")) {
      const many = key.replace(/_other$/, "_many");
      if (!(many in tree)) out[many] = value;
    }
  }
  return out;
}

const spanish = Object.fromEntries(Object.entries(es).map(([namespace, tree]) => [namespace, withManyForms(tree, "es")]));

/**
 * Spanish is bundled (default and fallback) and registered synchronously on import, so tests and
 * early code can call `t` right away. Other languages load on demand (`loadLanguage`).
 */
void i18n.use(initReactI18next).init({
  resources: { es: spanish },
  lng: DEFAULT_LANGUAGE,
  fallbackLng: DEFAULT_LANGUAGE,
  supportedLngs: ["es", "en"],
  ns: Object.keys(es),
  defaultNS: "shell",
  interpolation: { escapeValue: false },
  react: { useSuspense: false },
  initAsync: false,
});

/** Every namespace, so `t("area:path.to.key")` is checked against all the Spanish files. */
export type Namespace = keyof Resources;
export type TranslateFn = TFunction<Namespace[]>;

/** Translate function for code outside React components (always the active language). */
export const t = i18n.t.bind(i18n) as TranslateFn;

/**
 * The translation for a key built from a code the backend sends (an error class, a job error), or null
 * when that code has no text yet. Keys built this way are not checked by `tsc`; the caller supplies the
 * generic sentence.
 */
export function translateIfKnown(key: string): string | null {
  return i18n.exists(key) ? i18n.t(key as never) : null;
}

/**
 * `useTranslation` for the whole app: `const { t } = useT()` re-renders the component when the language
 * changes and accepts keys of every namespace, written `"area:path"`.
 */
export function useT() {
  return useTranslation<Namespace[]>();
}

const loaded = new Set<Language>([DEFAULT_LANGUAGE]);

/** Downloads a language bundle once; Spanish is already in the main bundle. */
export async function loadLanguage(language: Language): Promise<void> {
  if (loaded.has(language)) return;
  const { en } = await import("../locales/en");
  for (const [namespace, resources] of Object.entries(en)) {
    i18n.addResourceBundle("en", namespace, withManyForms(resources, "en"), true, true);
  }
  loaded.add(language);
}

/** Keeps `<html lang>` and the tab title in step with the active language. */
export function syncDocument(): void {
  if (typeof document === "undefined") return;
  document.documentElement.lang = i18n.language;
  document.title = i18n.t("shell:brand");
}

/** Switches the interface language: loads it, applies it, updates the document and remembers it. */
export async function setLanguage(language: Language, { persist = true }: { persist?: boolean } = {}): Promise<void> {
  await loadLanguage(language);
  await i18n.changeLanguage(language);
  syncDocument();
  if (persist) storeLanguage(language);
}

/** The language chosen in the desktop app's setup, or null in a browser, an older app or on failure. */
async function desktopLanguage(): Promise<string | null> {
  try {
    return (await desktopBridge()?.getLocale?.()) ?? null;
  } catch {
    return null;
  }
}

/**
 * Applies the saved, desktop-setup or browser language at start-up, before the first render. It is not
 * saved, so a later choice in the portal's own settings still wins. If the language cannot be loaded
 * the portal simply stays in Spanish.
 */
export async function initLanguage(): Promise<void> {
  try {
    await setLanguage(detectInitialLanguage(await desktopLanguage()), { persist: false });
  } catch {
    syncDocument();
  }
}

export default i18n;
