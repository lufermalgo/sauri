import React, { useId } from "react";
import { LANGUAGE_NAMES, SUPPORTED_LANGUAGES, isLanguage, setLanguage, useT, type Language } from "../i18n";

/**
 * Extension language choice (the options page is the one place to set it). Native radios give arrow
 * keys and form semantics. The choice is saved in `chrome.storage.local`; open panels and recorded
 * tabs follow it through `watchLanguage`.
 */
export function LanguageSelect() {
  const { t, i18n } = useT();
  const name = useId();
  const current: Language = isLanguage(i18n.language) ? i18n.language : "es";
  return <fieldset className="language-select panel-card panel-stack">
    <legend>{t("language:title")}</legend>
    <p>{t("language:help")}</p>
    <div className="language-options" role="radiogroup" aria-label={t("language:label")}>
      {SUPPORTED_LANGUAGES.map(language => <label key={language} lang={language}>
        <input type="radio" name={name} value={language} checked={current === language} onChange={() => { void setLanguage(language); }} />
        <span>{LANGUAGE_NAMES[language]}</span>
      </label>)}
    </div>
  </fieldset>;
}
