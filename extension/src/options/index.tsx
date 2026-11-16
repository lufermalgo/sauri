import React from "react";
import { createRoot } from "react-dom/client";
import { initLanguage, watchLanguage } from "../i18n";
import { OptionsApp } from "./OptionsApp";

const root = createRoot(document.getElementById("root")!);
void initLanguage().catch(() => {}).finally(() => {
  watchLanguage();
  root.render(<OptionsApp />);
});
