import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { OptionsApp } from "./OptionsApp";
import { permissionCopy as copy } from "./copy";

beforeEach(() => {
  vi.stubGlobal("chrome", { tabs: { getCurrent: vi.fn(async () => ({ id: 12 })), remove: vi.fn(async () => {}) } });
  vi.stubGlobal("navigator", {
    permissions: { query: vi.fn(async () => ({ state: "prompt" })) },
    mediaDevices: { getUserMedia: vi.fn() },
  });
});
afterEach(() => { cleanup(); vi.useRealTimers(); vi.unstubAllGlobals(); vi.restoreAllMocks(); });

describe("microphone permission page", () => {
  it("automatically asks from the options page and displays waiting while Chrome prompts", async () => {
    vi.mocked(navigator.mediaDevices.getUserMedia).mockImplementation(() => new Promise(() => {}));
    render(<OptionsApp />);
    expect(screen.getByText(copy.waiting)).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: copy.heading })).toBeInTheDocument();
    await waitFor(() => expect(navigator.mediaDevices.getUserMedia).toHaveBeenCalledWith({ audio: true }));
    expect(chrome.tabs.remove).not.toHaveBeenCalled();
  });
  it("releases the granted stream and uses the actual device label", async () => {
    const stop = vi.fn();
    vi.mocked(navigator.mediaDevices.getUserMedia).mockResolvedValue({ getTracks: () => [{ stop }], getAudioTracks: () => [{ label: "USB test" }] } as unknown as MediaStream);
    render(<OptionsApp />);
    expect(await screen.findByText(copy.granted)).toBeInTheDocument();
    expect(screen.getByText(`${copy.devicePrefix}USB test${copy.deviceSuffix}`)).toBeInTheDocument();
    expect(stop).toHaveBeenCalledOnce();
  });
  it("does not request again when already granted and closes only its own tab after three seconds", async () => {
    vi.useFakeTimers();
    vi.mocked(navigator.permissions.query).mockResolvedValue({ state: "granted" } as PermissionStatus);
    render(<OptionsApp />);
    await act(async () => {});
    expect(screen.getByText(copy.granted)).toBeInTheDocument();
    expect(navigator.mediaDevices.getUserMedia).not.toHaveBeenCalled();
    await act(async () => { await vi.advanceTimersByTimeAsync(2999); });
    expect(chrome.tabs.remove).not.toHaveBeenCalled();
    await act(async () => { await vi.advanceTimersByTimeAsync(1); });
    expect(chrome.tabs.getCurrent).toHaveBeenCalledOnce();
    expect(chrome.tabs.remove).toHaveBeenCalledWith(12);
  });
  it("closes immediately on request", async () => {
    vi.mocked(navigator.permissions.query).mockResolvedValue({ state: "granted" } as PermissionStatus);
    render(<OptionsApp />);
    fireEvent.click(await screen.findByRole("button", { name: copy.close }));
    await waitFor(() => expect(chrome.tabs.remove).toHaveBeenCalledWith(12));
  });
  it("displays denied steps and repeats permission checking on retry", async () => {
    vi.mocked(navigator.permissions.query).mockResolvedValue({ state: "denied" } as PermissionStatus);
    render(<OptionsApp />);
    expect(await screen.findByText(copy.denied)).toBeInTheDocument();
    expect(screen.getAllByRole("listitem")).toHaveLength(3);
    expect(navigator.mediaDevices.getUserMedia).not.toHaveBeenCalled();
    vi.mocked(navigator.permissions.query).mockResolvedValue({ state: "granted" } as PermissionStatus);
    fireEvent.click(screen.getByRole("button", { name: copy.retry }));
    expect(await screen.findByText(copy.granted)).toBeInTheDocument();
  });
  it("shows denied after the Chrome prompt is rejected", async () => {
    vi.mocked(navigator.mediaDevices.getUserMedia).mockRejectedValue(new DOMException("Synthetic", "NotAllowedError"));
    render(<OptionsApp />);
    expect(await screen.findByText(copy.denied)).toBeInTheDocument();
    expect(screen.queryByText("Synthetic")).not.toBeInTheDocument();
    expect(chrome.tabs.remove).not.toHaveBeenCalled();
  });
  it("shows localized device errors, not raw technical messages", async () => {
    vi.mocked(navigator.mediaDevices.getUserMedia).mockRejectedValue(new DOMException("Synthetic", "NotFoundError"));
    render(<OptionsApp />);
    expect(await screen.findByRole("alert")).toHaveTextContent(copy.deviceError);
  });
  it("releases a late granted stream after unmount", async () => {
    let resolve!: (stream: MediaStream) => void;
    const stop = vi.fn();
    vi.mocked(navigator.mediaDevices.getUserMedia).mockImplementation(() => new Promise(value => { resolve = value; }));
    const view = render(<OptionsApp />);
    await waitFor(() => expect(navigator.mediaDevices.getUserMedia).toHaveBeenCalledOnce());
    view.unmount();
    await act(async () => resolve({ getTracks: () => [{ stop }] } as unknown as MediaStream));
    expect(stop).toHaveBeenCalledOnce();
    expect(chrome.tabs.remove).not.toHaveBeenCalled();
  });
  it("cancels the automatic close on unmount", async () => {
    vi.useFakeTimers();
    vi.mocked(navigator.permissions.query).mockResolvedValue({ state: "granted" } as PermissionStatus);
    const view = render(<OptionsApp />);
    await act(async () => {});
    view.unmount();
    await act(async () => { await vi.advanceTimersByTimeAsync(4000); });
    expect(chrome.tabs.remove).not.toHaveBeenCalled();
  });
  it("reports close errors instead of selecting another tab", async () => {
    vi.mocked(navigator.permissions.query).mockResolvedValue({ state: "granted" } as PermissionStatus);
    vi.mocked(chrome.tabs.getCurrent).mockResolvedValue(undefined);
    render(<OptionsApp />);
    fireEvent.click(await screen.findByRole("button", { name: copy.close }));
    expect(await screen.findByRole("alert")).toHaveTextContent(copy.closeError);
    expect(chrome.tabs.remove).not.toHaveBeenCalled();
  });
});
