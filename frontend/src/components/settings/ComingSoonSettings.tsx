import { copy } from "../../copy/es";
import type { SettingsCategory } from "../../router";

/** Quiet placeholder for a category whose screen has not shipped yet: text only, no controls. */
export function ComingSoonSettings({ category }: { category: keyof typeof copy.settings.comingSoon & SettingsCategory }) {
  return <p className="settings-help settings-coming-soon">{copy.settings.comingSoon[category]}</p>;
}
