import { useId, useState } from "react";
import { Monitor, Moon, Sun } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { THEME_CHOICES, readAppliedTheme, setTheme, type ThemeChoice } from "../../theme";
import { useT } from "../../i18n";
import { LanguageSelect } from "../LanguageSelect";
import { Card, Icon } from "../ui";

const THEME_ICONS: Record<ThemeChoice, LucideIcon> = { system: Monitor, light: Sun, dark: Moon };

/** Language and theme (applied at once and remembered per device). */
export function AppearanceSettings() {
  const { t } = useT();
  const name = useId();
  const [theme, setThemeState] = useState<ThemeChoice>(readAppliedTheme);

  function choose(choice: ThemeChoice) {
    setTheme(choice);
    setThemeState(choice);
  }

  return (
    <div className="settings-stack">
      <Card className="settings-card" aria-labelledby={`${name}-language-title`}>
        <h3 id={`${name}-language-title`} className="settings-card-title">{t("language:title")}</h3>
        <LanguageSelect />
        <p className="settings-help">{t("language:help")}</p>
      </Card>
      <Card className="settings-card" aria-labelledby={`${name}-theme-title`}>
        <h3 id={`${name}-theme-title`} className="settings-card-title">{t("settings:appearance.themeTitle")}</h3>
        <fieldset className="settings-segmented" aria-label={t("settings:appearance.themeLabel")}>
          {THEME_CHOICES.map((choice) => (
            <label key={choice} className="settings-segment">
              <input
                type="radio"
                name={name}
                value={choice}
                checked={theme === choice}
                onChange={() => choose(choice)}
              />
              <Icon icon={THEME_ICONS[choice]} />
              <span>{t(`settings:appearance.themes.${choice}`)}</span>
            </label>
          ))}
        </fieldset>
        <p className="settings-help">{t("settings:appearance.themeHelp")}</p>
      </Card>
    </div>
  );
}
