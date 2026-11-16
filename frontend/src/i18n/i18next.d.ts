import type { Resources } from "../locales/es";

// A key that is not in the Spanish files (the source of truth) fails `tsc`.
declare module "i18next" {
  interface CustomTypeOptions {
    defaultNS: "shell";
    resources: Resources;
  }
}
