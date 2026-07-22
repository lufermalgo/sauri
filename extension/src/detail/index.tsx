// Detail_View for the transcript (detail.html, browser tab) — Req. 6.1, 6.2, 6.3
import React from "react";
import { createRoot } from "react-dom/client";
import { DetailApp } from "./DetailApp";

const root = createRoot(document.getElementById("root")!);
root.render(<DetailApp />);
