// Bundles the main process (ESM), the setup, portal and about preloads (CommonJS: sandboxed preloads cannot be ESM),
// the setup window and the «About Sauri» window (with the logo files from brand/) into dist/.
import fs from "node:fs";
import path from "node:path";
import { build } from "esbuild";

const root = path.resolve(import.meta.dirname, "..");
const out = path.join(root, "dist");
fs.rmSync(out, { recursive: true, force: true });
fs.mkdirSync(path.join(out, "setup"), { recursive: true });
fs.mkdirSync(path.join(out, "about"), { recursive: true });

const common = { bundle: true, sourcemap: true, logLevel: "warning" };
await build({
  ...common,
  entryPoints: [path.join(root, "src/main/main.ts")],
  outfile: path.join(out, "main.js"),
  platform: "node",
  target: "node22",
  format: "esm",
  external: ["electron"],
});
await build({
  ...common,
  entryPoints: [path.join(root, "src/setup/preload.ts")],
  outfile: path.join(out, "setup-preload.cjs"),
  platform: "node",
  target: "node22",
  format: "cjs",
  external: ["electron"],
});
await build({
  ...common,
  entryPoints: [path.join(root, "src/preload.ts")],
  outfile: path.join(out, "portal-preload.cjs"),
  platform: "node",
  target: "node22",
  format: "cjs",
  external: ["electron"],
});
await build({
  ...common,
  entryPoints: [path.join(root, "src/about/preload.ts")],
  outfile: path.join(out, "about-preload.cjs"),
  platform: "node",
  target: "node22",
  format: "cjs",
  external: ["electron"],
});
await build({
  ...common,
  entryPoints: [path.join(root, "src/setup/setup.ts")],
  outfile: path.join(out, "setup", "setup.js"),
  platform: "browser",
  target: "chrome130",
  format: "iife",
});
await build({
  ...common,
  entryPoints: [path.join(root, "src/about/about.ts")],
  outfile: path.join(out, "about", "about.js"),
  platform: "browser",
  target: "chrome130",
  format: "iife",
});
for (const file of ["index.html", "setup.css"]) {
  fs.copyFileSync(path.join(root, "src/setup", file), path.join(out, "setup", file));
}
for (const file of ["index.html", "about.css"]) {
  fs.copyFileSync(path.join(root, "src/about", file), path.join(out, "about", file));
}
for (const file of ["sauri-logo.svg", "sauri-logo-dark.svg"]) {
  fs.copyFileSync(path.join(root, "..", "brand", file), path.join(out, "about", file));
}
console.log("built desktop/dist");
