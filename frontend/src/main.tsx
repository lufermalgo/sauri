import React from "react";
import { createRoot } from "react-dom/client";
import "./index.css";
import { App } from "./App";
import { initLanguage } from "./i18n";
import { initTheme } from "./theme";

// index.html already applied the stored theme before the first paint; this keeps it in sync
// if that inline script was blocked.
initTheme();

const root = createRoot(document.getElementById("root")!);
// The saved or browser language is applied before the first paint, so there is no flash of Spanish.
void initLanguage().then(() => root.render(<App />));
