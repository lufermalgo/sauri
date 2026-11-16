import { afterEach } from "vitest";
import i18n, { setLanguage } from "../i18n";

// Tests assert Spanish text (the default language): import registers it, and any test that switches
// language gets Spanish back, so no test depends on the order the files run in.
afterEach(async () => {
  if (i18n.language !== "es") await setLanguage("es", { persist: false });
});
