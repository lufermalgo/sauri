import i18n from "./index";

/** Intl formatters for the active language. Dates, numbers and lists never get formatted by hand. */

const cache = new Map<string, unknown>();

function formatter<T>(kind: string, create: (locale: string) => T, options: unknown): T {
  const locale = i18n.language;
  const key = `${kind}|${locale}|${JSON.stringify(options ?? null)}`;
  let found = cache.get(key) as T | undefined;
  if (!found) {
    found = create(locale);
    cache.set(key, found);
  }
  return found;
}

export function formatNumber(value: number, options?: Intl.NumberFormatOptions): string {
  return formatter("number", (locale) => new Intl.NumberFormat(locale, options), options).format(value);
}

export function formatDate(value: Date | number, options?: Intl.DateTimeFormatOptions): string {
  return formatter("date", (locale) => new Intl.DateTimeFormat(locale, options), options).format(value);
}

/** "a, b and c" / "a, b y c". */
export function formatList(items: readonly string[], options?: Intl.ListFormatOptions): string {
  return formatter("list", (locale) => new Intl.ListFormat(locale, options), options).format(items);
}

/** Alphabetical order of two titles in the active language ("ñ" and accents sort as readers expect). */
export function compareText(a: string, b: string): number {
  return a.localeCompare(b, i18n.language);
}

/** Uppercases for the active language (initials, avatars). */
export function toUpperLocale(text: string): string {
  return text.toLocaleUpperCase(i18n.language);
}
