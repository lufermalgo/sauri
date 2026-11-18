/**
 * Language choice (see "Adding a text" in DESIGN.md). Spanish is the default
 * and the source language; the choice is remembered per browser in localStorage.
 */
export const SUPPORTED_LANGUAGES = ["es", "en"] as const;

export type Language = (typeof SUPPORTED_LANGUAGES)[number];

export const DEFAULT_LANGUAGE: Language = "es";

export const LANGUAGE_STORAGE_KEY = "sauri_language";

/** Each language written in itself, so a reader can always find theirs. */
// Endonyms are the one place Spanish text may live outside the translation files.
export const LANGUAGE_NAMES: Record<Language, string> = { es: "Español", en: "English" }; // i18n-ignore

export function isLanguage(value: unknown): value is Language {
  return SUPPORTED_LANGUAGES.includes(value as Language);
}

/** Maps a BCP 47 tag ("es-CO", "en_US", "EN") to a supported language, or null for any other. */
export function matchLanguage(tag: string | null | undefined): Language | null {
  const primary = (tag ?? "").trim().toLowerCase().split(/[-_]/)[0];
  return isLanguage(primary) ? primary : null;
}

interface DetectionInput {
  /** The language saved by the user, if any. */
  stored?: string | null;
  /** The language chosen in the desktop app's setup, when the portal runs inside the app. */
  desktop?: string | null;
  /** The browser's preferred languages, most preferred first (`navigator.languages`). */
  browserLanguages?: readonly string[];
}

/**
 * Saved choice first; then the desktop app's setup choice; otherwise the first browser-preferred language
 * that is supported (es* or en*); otherwise Spanish.
 */
export function detectLanguage({ stored, desktop, browserLanguages = [] }: DetectionInput): Language {
  const saved = matchLanguage(stored) ?? matchLanguage(desktop);
  if (saved) return saved;
  for (const tag of browserLanguages) {
    const match = matchLanguage(tag);
    if (match) return match;
  }
  return DEFAULT_LANGUAGE;
}

/** The saved language, or null when none is saved or storage is blocked. */
export function readStoredLanguage(): Language | null {
  try {
    return matchLanguage(localStorage.getItem(LANGUAGE_STORAGE_KEY));
  } catch {
    return null;
  }
}

/** Remembers a choice; with blocked storage it lasts until the page closes. */
export function storeLanguage(language: Language): void {
  try {
    localStorage.setItem(LANGUAGE_STORAGE_KEY, language);
  } catch {
    // Storage blocked: the choice still applies to this page.
  }
}

/** The language to start with, from the saved choice, the desktop app's setup and the browser's preferences. */
export function detectInitialLanguage(desktop?: string | null): Language {
  const browserLanguages = typeof navigator === "undefined"
    ? []
    : navigator.languages?.length ? navigator.languages : [navigator.language];
  return detectLanguage({ stored: readStoredLanguage(), desktop, browserLanguages });
}
