import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { copy } from "./copy";
import { installOverlayMessaging } from "./messaging";
import { cancelCountdown, hideRecordingUI } from "./recording";

type Listener = (message: Record<string, unknown>, sender: object, reply: (value: unknown) => void) => boolean | void;

let listeners: Listener[];
let runtimeId: string | undefined;
let recovery: { state?: object } | undefined;

function stubChrome() {
  vi.stubGlobal("chrome", {
    runtime: {
      get id() { return runtimeId; },
      onMessage: { addListener: (listener: Listener) => listeners.push(listener) },
      sendMessage: vi.fn(async (message: { type: string }) => (message.type === "get-recording-ui" ? recovery : { ok: true })),
    },
  });
}
function send(message: Record<string, unknown>, listener = listeners[0]) {
  return new Promise<unknown>(resolve => { if (!listener(message, {}, resolve)) resolve(undefined); });
}
const noticeText = () => document.getElementById("sauri-consent-banner-host")?.shadowRoot?.textContent ?? "";

beforeEach(() => {
  listeners = [];
  runtimeId = "extension-id";
  recovery = undefined;
  stubChrome();
});
afterEach(() => {
  cancelCountdown();
  hideRecordingUI();
  delete (globalThis as Record<string, unknown>).__sauriOverlayInstall;
  document.body.replaceChildren();
  vi.unstubAllGlobals();
});

describe("overlay messaging installation", () => {
  it("installs once per page, even if the script is injected again", () => {
    expect(installOverlayMessaging()).toBe(true);
    expect(installOverlayMessaging()).toBe(false);
    expect(listeners).toHaveLength(1);
  });

  it("replaces an installation whose extension context is gone and clears the controls it left", () => {
    expect(installOverlayMessaging()).toBe(true);
    const leftover = document.createElement("div");
    leftover.id = "sauri-recording-host";
    document.body.append(leftover);
    runtimeId = undefined;
    expect(installOverlayMessaging()).toBe(true);
    expect(listeners).toHaveLength(2);
    expect(document.getElementById("sauri-recording-host")).toBeNull();
  });

  it("shows the neutral tab notice outside Meet", async () => {
    installOverlayMessaging();
    await send({ type: "show-consent-banner" });
    expect(noticeText()).toContain(copy.tabNotice);
    expect(noticeText()).toContain(copy.tabNoticeHint);
    expect(noticeText()).not.toContain(copy.notice);
    expect(chrome.runtime.sendMessage).toHaveBeenCalledWith(expect.objectContaining({ type: "notification-emitted" }));
  });

  it("keeps the meeting notice on Google Meet", async () => {
    vi.stubGlobal("location", { hostname: "meet.google.com" });
    installOverlayMessaging();
    await send({ type: "show-consent-banner" });
    expect(noticeText()).toContain(copy.notice);
    expect(noticeText()).toContain(copy.noticeHint);
    expect(noticeText()).not.toContain(copy.tabNotice);
  });

  it("words the countdown for the host", async () => {
    installOverlayMessaging();
    const done = send({ type: "show-countdown", seconds: 3, requestId: "r" });
    const text = () => document.getElementById("sauri-countdown-host")!.shadowRoot!.textContent;
    expect(text()).toContain(copy.tabCountdownHint);
    expect(text()).not.toContain(copy.countdownHint);
    cancelCountdown();
    expect(await done).toEqual({ ok: false });
  });

  it("answers the page title only when the host provides one", async () => {
    installOverlayMessaging();
    expect(await send({ type: "get-current-title" })).toBeUndefined();
    listeners = [];
    delete (globalThis as Record<string, unknown>).__sauriOverlayInstall;
    installOverlayMessaging({ currentTitle: () => "Standup" });
    expect(await send({ type: "get-current-title" })).toEqual({ title: "Standup" });
  });

  it("restores the notice and controls from the recording state when it loads", async () => {
    recovery = { state: { sessionId: "s", paused: false, elapsedMs: 0, showControlBar: true } };
    installOverlayMessaging();
    await vi.waitFor(() => expect(document.getElementById("sauri-recording-host")).not.toBeNull());
    expect(noticeText()).toContain(copy.tabNotice);
  });

  it("stays silent when nothing is being recorded or the worker cannot answer", async () => {
    installOverlayMessaging();
    await vi.waitFor(() => expect(chrome.runtime.sendMessage).toHaveBeenCalledWith({ type: "get-recording-ui" }));
    expect(document.getElementById("sauri-recording-host")).toBeNull();
    vi.mocked(chrome.runtime.sendMessage).mockRejectedValueOnce(new Error("no worker"));
    delete (globalThis as Record<string, unknown>).__sauriOverlayInstall;
    expect(installOverlayMessaging()).toBe(true);
  });
});

describe("variants of the recording notice", () => {
  it("defaults to the meeting wording so existing Meet behavior is unchanged", async () => {
    const { showNotice } = await import("./recording");
    expect(showNotice()).toBe(true);
    expect(noticeText()).toContain(copy.notice);
  });
});
