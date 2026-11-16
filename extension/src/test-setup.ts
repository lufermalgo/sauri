// Global vitest configuration: jest-dom matchers for render tests.
import "@testing-library/jest-dom/vitest";
import { afterEach, beforeEach } from "vitest";
import { cleanup } from "@testing-library/react";
import i18n, { DEFAULT_LANGUAGE } from "./i18n";

// jsdom reports an English browser; tests run in the source language unless a test picks another.
beforeEach(() => {
  Object.defineProperty(window.navigator, "language", { value: "es-CO", configurable: true });
  Object.defineProperty(window.navigator, "languages", { value: ["es-CO"], configurable: true });
});

afterEach(async () => {
  cleanup();
  if (i18n.language !== DEFAULT_LANGUAGE) await i18n.changeLanguage(DEFAULT_LANGUAGE);
});
