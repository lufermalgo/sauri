import { fileURLToPath } from "node:url";
import { configDefaults, defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

export default defineConfig({
  // The public directory contains only the synthetic trial WAV. Vite builds
  // default to production mode; do not copy trial media into those builds.
  publicDir: process.env.NODE_ENV === "production" ? false : "public",
  plugins: [react()],
  test: {
    exclude: [...configDefaults.exclude, "tests/e2e/**"],
  },
  resolve: {
    alias: {
      "@sauri/shared-types": fileURLToPath(
        new URL("../packages/shared-types/src/index.ts", import.meta.url)
      ),
    },
  },
  build: {
    outDir: "dist",
  },
});
