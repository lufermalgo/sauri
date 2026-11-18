// Bundles the main process (ESM), the setup preload (CommonJS: sandboxed preloads cannot be ESM) and the setup
// window into dist/.
import fs from "node:fs";
import path from "node:path";
import { build } from "esbuild";

const root = path.resolve(import.meta.dirname, "..");
const out = path.join(root, "dist");
fs.rmSync(out, { recursive: true, force: true });
fs.mkdirSync(path.join(out, "setup"), { recursive: true });

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
  entryPoints: [path.join(root, "src/setup/setup.ts")],
  outfile: path.join(out, "setup", "setup.js"),
  platform: "browser",
  target: "chrome130",
  format: "iife",
});
for (const file of ["index.html", "setup.css"]) {
  fs.copyFileSync(path.join(root, "src/setup", file), path.join(out, "setup", file));
}
console.log("built desktop/dist");
