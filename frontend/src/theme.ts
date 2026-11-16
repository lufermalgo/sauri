/**
 * Theme preference (DESIGN.md 3.4). "system" leaves `<html data-theme>` unset so the interface
 * follows `prefers-color-scheme`; "light" and "dark" force a mode. The choice is remembered per
 * device in localStorage. `index.html` repeats the read below in an inline script so the stored
 * theme applies before the first paint; a test keeps the two in sync.
 */
export const THEME_STORAGE_KEY = "sauri_theme";

export type ThemeChoice = "system" | "light" | "dark";

export const THEME_CHOICES: readonly ThemeChoice[] = ["system", "light", "dark"];

function isThemeChoice(value: unknown): value is ThemeChoice {
  return THEME_CHOICES.includes(value as ThemeChoice);
}

/** The choice stored on this device, or "system" when none is stored or storage is blocked. */
export function readStoredTheme(): ThemeChoice {
  try {
    const stored = localStorage.getItem(THEME_STORAGE_KEY);
    return isThemeChoice(stored) ? stored : "system";
  } catch {
    return "system";
  }
}

/** The theme in effect right now, read from the document (works even when storage is blocked). */
export function readAppliedTheme(): ThemeChoice {
  const applied = document.documentElement.getAttribute("data-theme");
  return applied === "light" || applied === "dark" ? applied : "system";
}

/** Sets or clears `data-theme` on the root element. */
export function applyTheme(choice: ThemeChoice): void {
  if (choice === "system") document.documentElement.removeAttribute("data-theme");
  else document.documentElement.setAttribute("data-theme", choice);
}

/** Applies a choice now and remembers it; with blocked storage it lasts until the page closes. */
export function setTheme(choice: ThemeChoice): void {
  applyTheme(choice);
  try {
    localStorage.setItem(THEME_STORAGE_KEY, choice);
  } catch {
    // blocked storage: the choice only lasts for this visit
  }
}

/** Applies the stored choice at start-up. */
export function initTheme(): void {
  applyTheme(readStoredTheme());
}
