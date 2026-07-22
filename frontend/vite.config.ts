import { fileURLToPath } from "node:url";
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
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
