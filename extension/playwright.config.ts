import { defineConfig } from "@playwright/test";

// Real backend and authenticated portal against uniquely named Docker resources;
// globalSetup owns teardown even if setup or a test fails.
export default defineConfig({
  testDir: "./tests/e2e",
  timeout: 90_000,
  fullyParallel: false,
  workers: 1,
  reporter: [["list"]],
  globalSetup: "./tests/e2e/global-setup.ts",
});
