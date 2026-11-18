// `npm run desktop:dev`: builds the portal for same-origin serving, builds the app and runs it against the runtime
// cache and the repository sources, with its data in ~/Library/Application Support/Sauri-dev (SAURI_DEV=1).
import { spawn, spawnSync } from "node:child_process";
import os from "node:os";
import path from "node:path";

const root = path.resolve(import.meta.dirname, "..");
const repo = path.resolve(root, "..");
const runtime =
  process.env.SAURI_RUNTIME_DIR ?? path.join(os.homedir(), "Library", "Caches", "sauri-runtime-build", "runtime-current");
const portal = process.env.SAURI_PORTAL_DIR ?? path.join(root, ".dev-portal");

function run(command, args, options = {}) {
  const result = spawnSync(command, args, { stdio: "inherit", ...options });
  if (result.status !== 0) process.exit(result.status ?? 1);
}

if (!process.env.SAURI_PORTAL_DIR) {
  // The API serves the portal on its own origin, so the build calls the API with relative URLs.
  run("npm", ["run", "build", "-w", "frontend", "--", "--outDir", portal, "--emptyOutDir"], {
    cwd: repo,
    env: { ...process.env, VITE_API_BASE_URL: "" },
  });
}
run(process.execPath, [path.join(root, "scripts", "build.mjs")]);

const electron = path.join(repo, "node_modules", ".bin", "electron");
const child = spawn(electron, [root, ...process.argv.slice(2)], {
  stdio: "inherit",
  env: { ...process.env, SAURI_DEV: "1", SAURI_RUNTIME_DIR: runtime, SAURI_PORTAL_DIR: portal },
});
for (const signal of ["SIGINT", "SIGTERM"]) process.on(signal, () => child.kill(signal));
child.on("exit", (code) => process.exit(code ?? 0));
