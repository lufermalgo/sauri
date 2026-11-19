// Desktop texts: Spanish is the source language, English is available (Requirement 6.6).
import en from "./locales/en.json";
import es from "./locales/es.json";

export type Locale = "es" | "en";
export type MessageKey = keyof typeof es;

const CATALOGS: Record<Locale, Record<MessageKey, string>> = { es, en };

export function t(locale: Locale, key: MessageKey, vars: Record<string, string | number> = {}): string {
  const template = CATALOGS[locale][key] ?? CATALOGS.es[key];
  return template.replace(/\{(\w+)\}/g, (match, name: string) => (name in vars ? String(vars[name]) : match));
}

/** `_one` / `_other` pair chosen by count. */
export function plural(
  locale: Locale,
  base:
    | "tray.status.processing"
    | "quit.message"
    | "uninstall.processing"
    | "update.failed.processing"
    | "about.uptime.minutes"
    | "about.uptime.days",
  count: number,
): string {
  return t(locale, `${base}_${count === 1 ? "one" : "other"}` as MessageKey, { count });
}

export function formatGigabytes(locale: Locale, bytes: number): string {
  const value = new Intl.NumberFormat(locale, { maximumFractionDigits: 1 }).format(bytes / 1e9);
  return `${value} GB`;
}

export const catalogs = CATALOGS;
