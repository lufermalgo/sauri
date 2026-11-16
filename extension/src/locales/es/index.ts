import language from "./language.json";
import overlay from "./overlay.json";
import panel from "./panel.json";
import permission from "./permission.json";

/**
 * Spanish is the source language: its JSON files define the shape (and so the typed keys) that every
 * other language must match. One namespace per area; `src/i18n/index.ts` registers them.
 */
export const es = { language, overlay, panel, permission };

export type Resources = typeof es;
