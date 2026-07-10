import { defineConfig } from "vite";
import { crx } from "@crxjs/vite-plugin";
import { resolve } from "path";
import manifest from "./manifest.json";

export default defineConfig({
  plugins: [crx({ manifest })],
  build: {
    outDir: "dist",
    rollupOptions: {
      input: {
        offscreen: resolve(__dirname, "src/offscreen.html"),
        detail: resolve(__dirname, "src/detail/index.html"),
      },
    },
  },
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test-setup.ts"],
    // tests/e2e/** are Playwright specs (run via `npm run test:e2e`), not Vitest.
    exclude: ["node_modules/**", "tests/e2e/**"],
  },
});
