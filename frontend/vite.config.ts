import { fileURLToPath } from "node:url";
import { configDefaults, defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

export default defineConfig({
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
