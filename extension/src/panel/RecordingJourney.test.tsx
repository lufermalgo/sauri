import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { IDBFactory } from "fake-indexeddb";
import { SidePanelApp } from "./SidePanelApp";
import { panelCopy as copy } from "./copy";
import { DEFAULT_RECORDING_SETTINGS, parseRecordingSettings } from "./recordingSettings";
import type { RecordingSettings } from "../core/types";

let settings: RecordingSettings;
let listeners: Array<(changes: Record<string, chrome.storage.StorageChange>, area: string) => void>;

beforeEach(() => {
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
      local: { get: vi.fn(async () => ({ recordingSettings: settings })), set: vi.fn(async (value: { recordingSettings: RecordingSettings }) => { settings = value.recordingSettings; }) },
      sync: { get: vi.fn(async () => ({ authToken: "synthetic" })), remove: vi.fn(async () => {}), set: vi.fn(async () => {}) },
      session: { get: vi.fn(async () => ({ sauriState: { status: "idle" } })) },
      onChanged: { addListener: vi.fn(listener => listeners.push(listener)), removeListener: vi.fn() },
    },
    tabs: { query: vi.fn(async () => [{ url: "https://meet.google.com/test" }]), create: vi.fn(async () => ({})), onActivated: { addListener: vi.fn(), removeListener: vi.fn() }, onUpdated: { addListener: vi.fn(), removeListener: vi.fn() } },
  });
  vi.stubGlobal("fetch", vi.fn(async () => new Response("[]", { status: 200 })));
});
afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); });

async function ready() {
  const record = await screen.findByRole("button", { name: copy.record });
  await waitFor(() => expect(record).toBeEnabled());
  return record;
}
function project(state: unknown) {
  listeners.forEach(listener => listener({ sauriState: { newValue: state } }, "session"));
}

describe("Terra recording journey", () => {
  it("maps a real HTTP 401 to expired login rather than the technical history error", async () => {
    vi.mocked(fetch).mockResolvedValue(new Response("", { status: 401 }));
    render(<SidePanelApp />);
    expect(await screen.findByRole("heading", { name: copy.loginHeading })).toBeInTheDocument();
    expect(screen.getByText(copy.sessionExpired)).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent(copy.sessionAlert);
    expect(screen.queryByText(copy.listError)).not.toBeInTheDocument();
    expect(chrome.storage.sync.remove).toHaveBeenCalledWith("authToken");
    fireEvent.change(screen.getByLabelText(copy.email), { target: { value: "test@example.com" } });
    fireEvent.change(screen.getByLabelText(copy.password), { target: { value: "test" } });
    vi.mocked(fetch).mockResolvedValueOnce(new Response(JSON.stringify({ access_token: "synthetic-new", expires_in: 3600 }), { status: 200 })).mockResolvedValue(new Response("[]", { status: 200 }));
    fireEvent.click(screen.getByRole("button", { name: copy.login }));
    await ready();
    expect(screen.queryByText(copy.sessionExpired)).not.toBeInTheDocument();
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
    await waitFor(() => expect(chrome.storage.local.set).toHaveBeenCalledWith({ recordingSettings: { countdownSeconds: 10, showControlBar: false, skipMicWarning: true } }));
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
  it("reads and writes recordingSettings from the gear without opening the permission page", async () => {
    settings = { countdownSeconds: 5, showControlBar: false, skipMicWarning: true };
    render(<SidePanelApp />);
    await ready();
    fireEvent.click(screen.getByRole("button", { name: copy.settings }));
    expect(await screen.findByLabelText(copy.countdown)).toHaveValue("5");
    expect(screen.getByLabelText(copy.controlBar)).not.toBeChecked();
    fireEvent.change(screen.getByLabelText(copy.countdown), { target: { value: "10" } });
    await waitFor(() => expect(chrome.storage.local.set).toHaveBeenCalledWith({ recordingSettings: { ...settings, countdownSeconds: 10 } }));
    await waitFor(() => expect(screen.getByLabelText(copy.controlBar)).toBeEnabled());
    fireEvent.click(screen.getByLabelText(copy.controlBar));
    await waitFor(() => expect(settings).toEqual({ countdownSeconds: 10, showControlBar: true, skipMicWarning: true }));
    expect(chrome.runtime.openOptionsPage).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: copy.back }));
    expect(await ready()).toBeInTheDocument();
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
  it("does not invent elapsed time when reopening an active recording", async () => {
    vi.mocked(chrome.storage.session.get).mockImplementation(async () => ({ sauriState: { status: "recording", sessionId: "already-active" } }));
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
    fireEvent.click(screen.getByRole("radio", { name: copy.audioOnly }));
    await waitFor(() => expect(chrome.runtime.sendMessage).toHaveBeenCalledWith({ type: "set-capture-mode", captureMode: "audio_only" }));
    await waitFor(() => expect(screen.getByRole("radio", { name: copy.audioOnly })).toHaveAttribute("aria-checked", "true"));
  });
  it("validates invalid and partial settings independently", () => {
    expect(parseRecordingSettings(null)).toEqual(DEFAULT_RECORDING_SETTINGS);
    expect(parseRecordingSettings({ countdownSeconds: 9, showControlBar: false, skipMicWarning: "yes" })).toEqual({ countdownSeconds: 3, showControlBar: false, skipMicWarning: false });
  });
});
