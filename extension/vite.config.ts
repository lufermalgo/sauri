/// <reference types="vitest/config" />
import { defineConfig } from "vite";
import { crx } from "@crxjs/vite-plugin";
import { resolve } from "path";
import manifest from "./manifest.json";
import { minimalWebAccessibleResources } from "./build/minimal-war";

export default defineConfig({
  plugins: [crx({ manifest }), minimalWebAccessibleResources()],
  build: {
    outDir: "dist",
    rollupOptions: {
      input: {
        offscreen: resolve(__dirname, "src/offscreen.html"),
        detail: resolve(__dirname, "src/detail/index.html"),
        options: resolve(__dirname, "src/options/index.html"),
        ...(process.env.SAURI_E2E_BUILD === "1" ? { e2eFixture: resolve(__dirname, "src/e2e/fixture.html") } : {}),
      },
    },
  },
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test-setup.ts"],
    // The overlay imports tokens.css as text (`?raw`); vitest empties CSS files unless included.
    css: { include: [/core\/design\/tokens\.css/] },
    // tests/e2e/** are Playwright specs (run via `npm run test:e2e`), not Vitest.
    exclude: ["node_modules/**", "tests/e2e/**"],
  },
});
