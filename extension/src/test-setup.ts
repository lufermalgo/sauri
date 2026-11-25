// Global vitest configuration: jest-dom matchers for render tests.
import "@testing-library/jest-dom/vitest";
import { afterEach, beforeEach } from "vitest";
import { cleanup, configure } from "@testing-library/react";
import i18n, { DEFAULT_LANGUAGE } from "./i18n";

// The hosted CI runner (2 cores, every test file in parallel) can take longer than Testing Library's default
// 1 s to render the panel, which made a different SidePanelApp test time out on each run. 4 s keeps findBy/waitFor
// under vitest's 5 s test timeout.
configure({ asyncUtilTimeout: 4000 });

// jsdom reports an English browser; tests run in the source language unless a test picks another.
beforeEach(() => {
  Object.defineProperty(window.navigator, "language", { value: "es-CO", configurable: true });
  Object.defineProperty(window.navigator, "languages", { value: ["es-CO"], configurable: true });
});

afterEach(async () => {
  cleanup();
  if (i18n.language !== DEFAULT_LANGUAGE) await i18n.changeLanguage(DEFAULT_LANGUAGE);
});
