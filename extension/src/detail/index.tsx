// Vista_De_Detalle de transcripción (detail.html, pestaña del navegador) — Req. 6.1, 6.2, 6.3
import React from "react";
import { createRoot } from "react-dom/client";
import { DetailApp } from "./DetailApp";

const root = createRoot(document.getElementById("root")!);
root.render(<DetailApp />);
