import React from "react";
import { createRoot } from "react-dom/client";
import "./index.css";
import { App } from "./App";
import { initTheme } from "./theme";

// index.html already applied the stored theme before the first paint; this keeps it in sync
// if that inline script was blocked.
initTheme();

const root = createRoot(document.getElementById("root")!);
root.render(<App />);
