import i18n, { type TFunction } from "i18next";
import { initReactI18next, useTranslation } from "react-i18next";
import { en } from "../locales/en";
import { es, type Resources } from "../locales/es";
import {
  DEFAULT_LANGUAGE, LANGUAGE_STORAGE_KEY, SUPPORTED_LANGUAGES, detectInitialLanguage, matchLanguage, storeLanguage,
  type Language,
} from "./languages";

export * from "./languages";

/**
 * Both languages are bundled (the extension pages and the page overlay cannot load files on demand),
 * and registered synchronously on import, so tests and early code can call `t` right away. Spanish is
 * the default and the fallback.
 */
void i18n.use(initReactI18next).init({
  resources: { es, en },
  lng: DEFAULT_LANGUAGE,
  fallbackLng: DEFAULT_LANGUAGE,
  supportedLngs: [...SUPPORTED_LANGUAGES],
  ns: Object.keys(es),
  defaultNS: "panel",
  interpolation: { escapeValue: false },
  react: { useSuspense: false },
  initAsync: false,
});

export type Namespace = keyof Resources;
export type TranslateFn = TFunction<Namespace[]>;

/** Translate function for code outside React components (always the active language). */
export const t = i18n.t.bind(i18n) as TranslateFn;

/** `useTranslation` for the whole extension: `const { t } = useT()` re-renders on a language change. */
export function useT() {
  return useTranslation<Namespace[]>();
}

/** Keeps `<html lang>` in step with the active language (extension pages only). */
export function syncDocument(): void {
  if (typeof document === "undefined") return;
  document.documentElement.lang = i18n.language;
}

/** Switches the interface language and, unless told otherwise, remembers it. */
export async function setLanguage(language: Language, { persist = true }: { persist?: boolean } = {}): Promise<void> {
  await i18n.changeLanguage(language);
  syncDocument();
  if (persist) await storeLanguage(language);
}

/** Applies the saved or browser language at start-up, before the first render. */
export async function initLanguage(): Promise<void> {
  await setLanguage(await detectInitialLanguage(), { persist: false });
}

/**
 * Follows a language chosen in another extension page (the options page), so an open panel or a
 * recorded tab switches without a reload. Returns the function that stops listening.
 */
export function watchLanguage(): () => void {
  const listener = (changes: Record<string, chrome.storage.StorageChange>, area: string) => {
    if (area !== "local" || !(LANGUAGE_STORAGE_KEY in changes)) return;
    const next = matchLanguage(changes[LANGUAGE_STORAGE_KEY].newValue as string | undefined);
    if (next) void setLanguage(next, { persist: false });
  };
  try {
    chrome.storage.onChanged.addListener(listener);
    return () => chrome.storage.onChanged.removeListener(listener);
  } catch {
    return () => {};
  }
}

export default i18n;
