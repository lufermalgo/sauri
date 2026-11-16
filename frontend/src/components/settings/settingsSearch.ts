import { copy } from "../../copy/es";
import { SETTINGS_GROUPS, type SettingsCategory, type SettingsGroupId } from "../../router";

/** Lowercase without accents, so an unaccented query finds an accented label. */
export function normalizeSearchText(value: string): string {
  return value.normalize("NFD").replace(/\p{M}/gu, "").toLowerCase();
}

function matches(category: SettingsCategory, tokens: string[]): boolean {
  const entry = copy.settings.categories[category];
  const haystack = normalizeSearchText(`${entry.label} ${entry.description} ${entry.keywords}`);
  return tokens.every((token) => haystack.includes(token));
}

export interface VisibleGroup {
  id: SettingsGroupId;
  categories: SettingsCategory[];
}

/** Groups with the categories that match every word of the query; empty groups are dropped. */
export function filterSettingsGroups(query: string): VisibleGroup[] {
  const tokens = normalizeSearchText(query).split(/\s+/).filter(Boolean);
  return SETTINGS_GROUPS.map((group) => ({
    id: group.id,
    categories: (group.categories as readonly SettingsCategory[]).filter((name) => matches(name, tokens)),
  })).filter((group) => group.categories.length > 0);
}
