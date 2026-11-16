/**
 * Language choice. Spanish is the default and the source language. The extension does not share storage
 * with the portal (another origin), so it keeps its own preference in `chrome.storage.local` and, when
 * none is saved, follows the browser's interface language (`chrome.i18n.getUILanguage()`).
 */
export const SUPPORTED_LANGUAGES = ["es", "en"] as const;

export type Language = (typeof SUPPORTED_LANGUAGES)[number];

export const DEFAULT_LANGUAGE: Language = "es";

/** `chrome.storage.local` key of the saved language. */
export const LANGUAGE_STORAGE_KEY = "sauriLanguage";

/** Each language written in itself, so a reader can always find theirs. */
// Endonyms are the one place Spanish text may live outside the translation files.
export const LANGUAGE_NAMES: Record<Language, string> = { es: "Español", en: "English" }; // i18n-ignore

export function isLanguage(value: unknown): value is Language {
  return SUPPORTED_LANGUAGES.includes(value as Language);
}

/** Maps a BCP 47 tag ("es-419", "en_US", "EN") to a supported language, or null for any other. */
export function matchLanguage(tag: string | null | undefined): Language | null {
  const primary = (tag ?? "").trim().toLowerCase().split(/[-_]/)[0];
  return isLanguage(primary) ? primary : null;
}

interface DetectionInput {
  /** The language saved by the user, if any. */
  stored?: string | null;
  /** The browser's interface language (`chrome.i18n.getUILanguage()`). */
  browserLanguage?: string | null;
}

/** Saved choice first; otherwise the browser's language if supported (es* or en*); otherwise Spanish. */
export function detectLanguage({ stored, browserLanguage }: DetectionInput): Language {
  return matchLanguage(stored) ?? matchLanguage(browserLanguage) ?? DEFAULT_LANGUAGE;
}

/** The saved language, or null when none is saved or storage is unavailable. */
export async function readStoredLanguage(): Promise<Language | null> {
  try {
    const stored = await chrome.storage.local.get(LANGUAGE_STORAGE_KEY);
    return matchLanguage(stored?.[LANGUAGE_STORAGE_KEY] as string | undefined);
  } catch {
    return null;
  }
}

/** Remembers a choice. Resolves false when the storage refused it (the choice still applies to this page). */
export async function storeLanguage(language: Language): Promise<boolean> {
  try {
    await chrome.storage.local.set({ [LANGUAGE_STORAGE_KEY]: language });
    return true;
  } catch {
    return false;
  }
}

export function browserUiLanguage(): string | null {
  try {
    return chrome.i18n.getUILanguage();
  } catch {
    return typeof navigator === "undefined" ? null : navigator.language;
  }
}

/** The language to start with, from the saved choice and the browser's interface language. */
export async function detectInitialLanguage(): Promise<Language> {
  return detectLanguage({ stored: await readStoredLanguage(), browserLanguage: browserUiLanguage() });
}
