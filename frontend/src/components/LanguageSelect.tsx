import { useId, useState } from "react";
import { LANGUAGE_NAMES, SUPPORTED_LANGUAGES, isLanguage, setLanguage, t as translate, useT, type Language } from "../i18n";
import "../styles/settings.css";

/**
 * Interface language choice: native radios (arrow keys and form semantics for free) in the same
 * segmented look as the theme choice. The result is announced in the language just chosen.
 */
export function LanguageSelect({ className = "" }: { className?: string }) {
  const { t, i18n } = useT();
  const name = useId();
  const [announcement, setAnnouncement] = useState("");
  const current: Language = isLanguage(i18n.language) ? i18n.language : "es";

  async function choose(next: Language) {
    try {
      await setLanguage(next);
    } catch {
      return; // the other language could not be loaded: the interface stays as it was
    }
    setAnnouncement(translate("language:changed", { language: LANGUAGE_NAMES[next] }));
  }

  return (
    <>
      <fieldset className={`settings-segmented ${className}`.trim()} aria-label={t("language:label")}>
        {SUPPORTED_LANGUAGES.map((language) => (
          <label key={language} className="settings-segment" lang={language}>
            <input
              type="radio"
              name={name}
              value={language}
              checked={current === language}
              onChange={() => void choose(language)}
            />
            <span>{LANGUAGE_NAMES[language]}</span>
          </label>
        ))}
      </fieldset>
      <span className="language-announcer" role="status">{announcement}</span>
    </>
  );
}
