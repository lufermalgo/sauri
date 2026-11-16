import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { ensureOverlay } from "./overlay-injection";

const executeScript = vi.fn();
beforeEach(() => {
  executeScript.mockReset().mockResolvedValue([]);
  vi.stubGlobal("chrome", { scripting: { executeScript } });
  vi.spyOn(console, "warn").mockImplementation(() => undefined);
});
afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks(); });

it("injects the standalone overlay script into an ordinary tab, top frame only", async () => {
  expect(await ensureOverlay(5, "https://example.com/talk")).toBe(true);
  expect(executeScript).toHaveBeenCalledOnce();
  const [injection] = executeScript.mock.calls[0];
  expect(injection).toEqual({ target: { tabId: 5 }, files: [expect.stringContaining("entry")] });
  expect(injection.target).not.toHaveProperty("allFrames");
});

it("leaves Meet to its static content script", async () => {
  expect(await ensureOverlay(5, "https://meet.google.com/abc-defg-hij")).toBe(true);
  expect(executeScript).not.toHaveBeenCalled();
});

it.each([undefined, "chrome://extensions", "file:///talk.html", "https://chromewebstore.google.com/x"])(
  "does not even try on the restricted page %s", async url => {
    expect(await ensureOverlay(5, url)).toBe(false);
    expect(executeScript).not.toHaveBeenCalled();
  });

it("reports an unavailable overlay instead of throwing when Chrome refuses", async () => {
  executeScript.mockRejectedValue(new Error("Cannot access contents of the page. Extension manifest must request permission"));
  expect(await ensureOverlay(5, "https://example.com/doc.pdf")).toBe(false);
});

it("reports an unavailable overlay when the scripting API is missing", async () => {
  vi.stubGlobal("chrome", {});
  expect(await ensureOverlay(5, "https://example.com/")).toBe(false);
});

it("can be called repeatedly for the same tab; the script guards against duplicates itself", async () => {
  await ensureOverlay(5, "https://example.com/");
  await ensureOverlay(5, "https://example.com/");
  expect(executeScript).toHaveBeenCalledTimes(2);
});
