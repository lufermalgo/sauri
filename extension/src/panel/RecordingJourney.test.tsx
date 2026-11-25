import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { sauriHealth } from "../test-backend";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { IDBFactory } from "fake-indexeddb";
import { SidePanelApp } from "./SidePanelApp";
import { panelCopy as copy } from "../i18n/spanish";
import { chooseSource, sourceTrigger } from "./test-helpers";
import { DEFAULT_RECORDING_SETTINGS, parseRecordingSettings } from "./recordingSettings";
import type { RecordingSettings } from "../core/types";

let settings: RecordingSettings;
let sessionStore: Record<string, unknown>;
let listeners: Array<(changes: Record<string, chrome.storage.StorageChange>, area: string) => void>;

beforeEach(() => {
  sessionStore = {};
  settings = { ...DEFAULT_RECORDING_SETTINGS };
  listeners = [];
  vi.stubGlobal("indexedDB", new IDBFactory());
  Object.defineProperty(HTMLDialogElement.prototype, "showModal", { configurable: true, value: function (this: HTMLDialogElement) { this.open = true; } });
  Object.defineProperty(HTMLDialogElement.prototype, "close", { configurable: true, value: function (this: HTMLDialogElement) { this.open = false; } });
  vi.stubGlobal("navigator", {
    permissions: { query: vi.fn(async () => ({ state: "granted" })) },
    mediaDevices: { enumerateDevices: vi.fn(async () => [{ kind: "audioinput", deviceId: "mic-test", label: "USB" }]), getUserMedia: vi.fn() },
  });
  vi.stubGlobal("chrome", {
    runtime: { openOptionsPage: vi.fn(async () => {}), sendMessage: vi.fn(async () => ({ ok: true })) },
    storage: {
      local: { setAccessLevel: vi.fn(async () => {}), get: vi.fn(async () => ({ sauriLocalToken: "synthetic-local", recordingSettings: settings })), set: vi.fn(async (value: { recordingSettings: RecordingSettings }) => { settings = value.recordingSettings; }), remove: vi.fn(async () => undefined) },
      session: {
        get: vi.fn(async () => ({ sauriState: { status: "idle" }, ...sessionStore })),
        set: vi.fn(async (value: Record<string, unknown>) => { Object.assign(sessionStore, value); }),
        remove: vi.fn(async (key: string) => { delete sessionStore[key]; }),
      },
      onChanged: { addListener: vi.fn(listener => listeners.push(listener)), removeListener: vi.fn() },
    },
    tabs: { query: vi.fn(async () => [{ url: "https://meet.google.com/test" }]), create: vi.fn(async () => ({})), onActivated: { addListener: vi.fn(), removeListener: vi.fn() }, onUpdated: { addListener: vi.fn(), removeListener: vi.fn() } },
  });
  vi.stubGlobal("fetch", vi.fn(async () => new Response("[]", { status: 200 })));
});
// Vitest runs afterEach hooks in stack order, so this hook runs before the setup file's cleanup():
// unmount first, while the chrome stub that the panel's effect cleanups use still exists.
afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });

async function ready() {
  const record = await screen.findByRole("button", { name: copy.newRecording });
  await waitFor(() => expect(record).toBeEnabled());
  return record;
}
function project(state: unknown) {
  listeners.forEach(listener => listener({ sauriState: { newValue: state } }, "session"));
}

describe("Terra recording journey", () => {
  it("keeps recording available when local pairing is refused, without a login form", async () => {
    vi.mocked(fetch).mockImplementation(async url => String(url).endsWith("/health")
      ? sauriHealth() : new Response("", { status: 403 }));
    render(<SidePanelApp />);
    await ready();
    expect(await screen.findByText(copy.listError)).toBeInTheDocument();
    expect(screen.queryByLabelText(/password|correo/i)).not.toBeInTheDocument();
  });
  it.each([false, true])("warns about a disabled microphone unless skipped=%s", async skip => {
    settings.skipMicWarning = skip;
    render(<SidePanelApp />);
    const record = await ready();
    fireEvent.click(screen.getByRole("switch", { name: copy.microphone }));
    fireEvent.click(record);
    if (!skip) {
      expect(await screen.findByRole("dialog")).toBeInTheDocument();
      expect(screen.getByText(copy.micOffDescription)).toBeInTheDocument();
      expect(chrome.runtime.sendMessage).not.toHaveBeenCalled();
      fireEvent.click(screen.getByRole("button", { name: copy.withoutMic }));
    } else expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    await waitFor(() => expect(chrome.runtime.sendMessage).toHaveBeenCalledWith(expect.objectContaining({ type: "start-capture", micDeviceId: null })));
    expect(navigator.permissions.query).not.toHaveBeenCalled();
  });
  it("persists skipMicWarning without changing the other recording settings", async () => {
    settings.countdownSeconds = 10;
    settings.showControlBar = false;
    render(<SidePanelApp />);
    const record = await ready();
    fireEvent.click(screen.getByRole("switch", { name: copy.microphone }));
    fireEvent.click(record);
    fireEvent.click(await screen.findByLabelText(copy.skipWarning));
    fireEvent.click(screen.getByRole("button", { name: copy.withoutMic }));
    await waitFor(() => expect(chrome.storage.local.set).toHaveBeenCalledWith({ recordingSettings: { countdownSeconds: 10, resolution: "720p", showControlBar: false, skipMicWarning: true } }));
    await waitFor(() => expect(chrome.runtime.sendMessage).toHaveBeenCalledOnce());
  });
  it("enables the microphone from the warning but never bypasses permission", async () => {
    vi.mocked(navigator.permissions.query).mockResolvedValue({ state: "prompt" } as PermissionStatus);
    render(<SidePanelApp />);
    const record = await ready();
    fireEvent.click(screen.getByRole("switch", { name: copy.microphone }));
    fireEvent.click(record);
    fireEvent.click(await screen.findByRole("button", { name: copy.enableMic }));
    await waitFor(() => expect(chrome.runtime.openOptionsPage).toHaveBeenCalledOnce());
    expect(chrome.runtime.sendMessage).not.toHaveBeenCalled();
    expect(screen.getByRole("alert")).toHaveTextContent(copy.permissionNeeded);
  });
  it("dismisses the microphone warning without starting a recording", async () => {
    render(<SidePanelApp />);
    const record = await ready();
    fireEvent.click(screen.getByRole("switch", { name: copy.microphone }));
    fireEvent.click(record);
    const dialog = await screen.findByRole("dialog");
    fireEvent(dialog, new Event("cancel", { cancelable: true }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(chrome.runtime.sendMessage).not.toHaveBeenCalled();
  });
  it("cannot dismiss a confirmed warning while its setting is being persisted", async () => {
    let resolve!: () => void;
    vi.mocked(chrome.storage.local.set).mockImplementation(() => new Promise<void>(done => { resolve = done; }));
    render(<SidePanelApp />);
    const record = await ready();
    fireEvent.click(screen.getByRole("switch", { name: copy.microphone }));
    fireEvent.click(record);
    fireEvent.click(await screen.findByLabelText(copy.skipWarning));
    fireEvent.click(screen.getByRole("button", { name: copy.withoutMic }));
    await waitFor(() => expect(chrome.storage.local.set).toHaveBeenCalledOnce());
    expect(fireEvent(screen.getByRole("dialog"), new Event("cancel", { cancelable: true }))).toBe(false);
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(chrome.runtime.sendMessage).not.toHaveBeenCalled();
    await act(async () => resolve());
    await waitFor(() => expect(chrome.runtime.sendMessage).toHaveBeenCalledWith(expect.objectContaining({ type: "start-capture", micDeviceId: null })));
  });
  it("reads and writes recordingSettings from the settings menu without opening the permission page", async () => {
    settings = { countdownSeconds: 5, resolution: "1080p", showControlBar: false, skipMicWarning: true };
    render(<SidePanelApp />);
    await ready();
    fireEvent.click(screen.getByRole("button", { name: copy.settings }));
    expect(await screen.findByLabelText(copy.countdown)).toHaveValue("5");
    expect(screen.getByLabelText(copy.resolution)).toHaveValue("1080p");
    expect(screen.getByRole("switch", { name: copy.controlBar })).toHaveAttribute("aria-checked", "false");
    expect(screen.getByRole("switch", { name: copy.micWarning })).toHaveAttribute("aria-checked", "false");
    fireEvent.change(screen.getByLabelText(copy.countdown), { target: { value: "10" } });
    await waitFor(() => expect(chrome.storage.local.set).toHaveBeenCalledWith({ recordingSettings: { ...settings, countdownSeconds: 10 } }));
    fireEvent.click(screen.getByRole("switch", { name: copy.controlBar }));
    await waitFor(() => expect(settings).toEqual({ countdownSeconds: 10, resolution: "1080p", showControlBar: true, skipMicWarning: true }));
    expect(chrome.runtime.openOptionsPage).not.toHaveBeenCalled();
    expect(screen.getByRole("dialog", { name: copy.settings })).toBeInTheDocument();
  });
  it.each([0, 3, 5, 10])("persists a %s s countdown", async seconds => {
    settings.countdownSeconds = seconds === 3 ? 5 : 3;
    render(<SidePanelApp />);
    await ready();
    fireEvent.click(screen.getByRole("button", { name: copy.settings }));
    fireEvent.change(await screen.findByLabelText(copy.countdown), { target: { value: String(seconds) } });
    await waitFor(() => expect(settings.countdownSeconds).toBe(seconds));
    expect(screen.getByLabelText(copy.countdown)).toHaveValue(String(seconds));
  });
  it.each([["480p", { width: 854, height: 480 }], ["720p", { width: 1280, height: 720 }], ["1080p", { width: 1920, height: 1080 }]] as const)("persists %s and sends its dimensions with start-capture", async (resolution, dimensions) => {
    settings.resolution = resolution === "720p" ? "1080p" : "720p";
    render(<SidePanelApp />);
    const record = await ready();
    fireEvent.click(screen.getByRole("button", { name: copy.settings }));
    fireEvent.change(await screen.findByLabelText(copy.resolution), { target: { value: resolution } });
    await waitFor(() => expect(settings.resolution).toBe(resolution));
    fireEvent.click(record);
    await waitFor(() => expect(chrome.runtime.sendMessage).toHaveBeenCalledWith(expect.objectContaining({ type: "start-capture", resolution: dimensions })));
  });
  it("maps the microphone-warning switch inversely to skipMicWarning and keeps the dialog working", async () => {
    render(<SidePanelApp />);
    const record = await ready();
    fireEvent.click(screen.getByRole("button", { name: copy.settings }));
    const warning = await screen.findByRole("switch", { name: copy.micWarning });
    expect(warning).toHaveAttribute("aria-checked", "true");
    fireEvent.click(warning);
    await waitFor(() => expect(settings.skipMicWarning).toBe(true));
    expect(screen.getByRole("switch", { name: copy.micWarning })).toHaveAttribute("aria-checked", "false");
    fireEvent.click(screen.getByRole("switch", { name: copy.microphone }));
    fireEvent.click(record);
    await waitFor(() => expect(chrome.runtime.sendMessage).toHaveBeenCalledWith(expect.objectContaining({ type: "start-capture", micDeviceId: null })));
    expect(screen.queryByRole("dialog", { name: copy.micOffHeading })).not.toBeInTheDocument();
    await waitFor(() => expect(screen.getByRole("button", { name: copy.settings })).toBeEnabled());
    fireEvent.click(screen.getByRole("button", { name: copy.settings }));
    fireEvent.click(await screen.findByRole("switch", { name: copy.micWarning }));
    await waitFor(() => expect(settings.skipMicWarning).toBe(false));
  });
  it("reports persistence failure without pretending settings were saved", async () => {
    vi.mocked(chrome.storage.local.set).mockRejectedValue(new Error("synthetic"));
    render(<SidePanelApp />);
    await ready();
    fireEvent.click(screen.getByRole("button", { name: copy.settings }));
    fireEvent.change(screen.getByLabelText(copy.countdown), { target: { value: "10" } });
    expect(await screen.findByRole("alert")).toHaveTextContent(copy.settingsError);
    expect(screen.getByLabelText(copy.countdown)).toHaveValue("3");
  });
  it("applies two quick changes in order without losing the first", async () => {
    render(<SidePanelApp />);
    await ready();
    fireEvent.click(screen.getByRole("button", { name: copy.settings }));
    fireEvent.change(await screen.findByLabelText(copy.countdown), { target: { value: "10" } });
    fireEvent.change(screen.getByLabelText(copy.resolution), { target: { value: "480p" } });
    await waitFor(() => expect(settings).toMatchObject({ countdownSeconds: 10, resolution: "480p" }));
  });
  it("locks countdown and resolution while recording but still applies the control bar live", async () => {
    render(<SidePanelApp />);
    await ready();
    await act(async () => project({ status: "recording", sessionId: "s-live" }));
    fireEvent.click(screen.getByRole("button", { name: copy.settings }));
    expect(await screen.findByLabelText(copy.countdown)).toBeDisabled();
    expect(screen.getByLabelText(copy.resolution)).toBeDisabled();
    expect(screen.getByText(copy.settingsLocked)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("switch", { name: copy.controlBar }));
    await waitFor(() => expect(settings.showControlBar).toBe(false));
    await waitFor(() => expect(chrome.runtime.sendMessage).toHaveBeenCalledWith({ type: "recording-settings-changed" }));
  });
  it("does not ping the service worker when the control bar changes while idle", async () => {
    render(<SidePanelApp />);
    await ready();
    fireEvent.click(screen.getByRole("button", { name: copy.settings }));
    fireEvent.click(await screen.findByRole("switch", { name: copy.controlBar }));
    await waitFor(() => expect(settings.showControlBar).toBe(false));
    expect(chrome.runtime.sendMessage).not.toHaveBeenCalledWith({ type: "recording-settings-changed" });
  });
  it("does not invent elapsed time when reopening an active recording", async () => {
    vi.mocked(chrome.storage.session.get).mockImplementation(async () => ({ sauriState: { status: "recording", sessionId: "already-active" }, ...sessionStore }));
    render(<SidePanelApp />);
    await screen.findByRole("button", { name: copy.stop });
    expect(screen.getByText("--:--")).toBeInTheDocument();
    expect(screen.queryByText("00:00")).not.toBeInTheDocument();
  });
  it("sends pause, resume and cancel without optimistic state or upload", async () => {
    render(<SidePanelApp />);
    await ready();
    await act(async () => project({ status: "recording", sessionId: "s-test", meetingTitle: "Meet test", micDeviceId: "mic-test", videoPresence: "muxed" }));
    expect(screen.getByText(`${copy.tab} Meet test`)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: copy.pause }));
    await waitFor(() => expect(chrome.runtime.sendMessage).toHaveBeenLastCalledWith({ type: "pause-capture" }));
    expect(screen.getByRole("button", { name: copy.pause })).toBeInTheDocument();
    await act(async () => project({ status: "recording", sessionId: "s-test", paused: true }));
    fireEvent.click(screen.getByRole("button", { name: copy.resume }));
    await waitFor(() => expect(chrome.runtime.sendMessage).toHaveBeenLastCalledWith({ type: "resume-capture" }));
    await waitFor(() => expect(screen.getByRole("button", { name: copy.discard })).toBeEnabled());
    fireEvent.click(screen.getByRole("button", { name: copy.discard }));
    await waitFor(() => expect(chrome.runtime.sendMessage).toHaveBeenLastCalledWith({ type: "cancel-capture" }));
    expect(chrome.runtime.sendMessage).not.toHaveBeenCalledWith({ type: "stop-capture" });
  });
  it("sends the existing stop message and shows a rejected control as an error", async () => {
    render(<SidePanelApp />);
    await ready();
    await act(async () => project({ status: "recording", sessionId: "s-test" }));
    vi.mocked(chrome.runtime.sendMessage).mockResolvedValue({ ok: false });
    fireEvent.click(screen.getByRole("button", { name: copy.stop }));
    expect(await screen.findByRole("alert")).toHaveTextContent(copy.commandError);
    expect(chrome.runtime.sendMessage).toHaveBeenCalledWith({ type: "stop-capture" });
    expect(screen.getByRole("button", { name: copy.stop })).toBeInTheDocument();
  });
  it("uses the existing capture-mode message", async () => {
    render(<SidePanelApp />);
    await ready();
    await chooseSource(copy.audioOnly);
    await waitFor(() => expect(chrome.runtime.sendMessage).toHaveBeenCalledWith({ type: "set-capture-mode", captureMode: "audio_only" }));
    await waitFor(() => expect(sourceTrigger()).toHaveTextContent(copy.audioOnly));
  });
  it("validates invalid and partial settings independently", () => {
    expect(parseRecordingSettings(null)).toEqual(DEFAULT_RECORDING_SETTINGS);
    expect(parseRecordingSettings({ countdownSeconds: 9, resolution: "4k", showControlBar: false, skipMicWarning: "yes" })).toEqual({ countdownSeconds: 3, resolution: "720p", showControlBar: false, skipMicWarning: false });
  });
});
