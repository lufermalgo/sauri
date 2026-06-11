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
      },
    },
  },
});
