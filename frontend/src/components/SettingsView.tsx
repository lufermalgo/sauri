import { copy } from "../copy/es";

/** Settings console. It has no options yet, so it only says so. */
export function SettingsView() {
  return (
    <section className="shell-page" aria-labelledby="settings-title">
      <h1 id="settings-title" className="shell-page-title">{copy.settings.title}</h1>
      <p className="shell-page-text">{copy.settings.empty}</p>
    </section>
  );
}
