import { describe, it, expect, vi } from "vitest";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { CaptureControls, type CaptureControlsProps } from "./CaptureControls";
import { panelCopy as copy } from "../../i18n/spanish";
const defaults: CaptureControlsProps = { captureState: "idle", microphones: [], onToggleCapture: vi.fn(), elapsedTimeMs: 0 };

function sourceButton() { return within(screen.getByRole("group", { name: copy.sourceMenu })).getAllByRole("button")[0]; }

describe("CaptureControls", () => {
  it("renders the compact control row and the primary button without title or subtitle", () => {
    render(<CaptureControls {...defaults} />);
    expect(screen.queryByRole("heading")).not.toBeInTheDocument();
    expect(sourceButton()).toHaveTextContent(copy.screenAudio);
    expect(sourceButton()).toHaveAttribute("aria-haspopup", "menu");
    expect(sourceButton()).toHaveAttribute("aria-expanded", "false");
    expect(screen.getByRole("switch", { name: copy.microphone })).toHaveAttribute("aria-checked", "true");
    expect(screen.getByRole("button", { name: copy.microphoneSelector })).toBeDisabled();
    expect(screen.getByRole("button", { name: copy.settings })).toBeEnabled();
    expect(screen.getByRole("button", { name: copy.newRecording })).toBeEnabled();
  });
  it("offers the three sources and reports the chosen one, disabling the tab when unavailable", () => {
    const onChangeSource = vi.fn();
    const view = render(<CaptureControls {...defaults} onChangeSource={onChangeSource} />);
    fireEvent.click(sourceButton());
    expect(sourceButton()).toHaveAttribute("aria-expanded", "true");
    expect(screen.getAllByRole("menuitemradio").map(item => item.textContent)).toEqual([copy.screenAudio, copy.audioOnly, copy.currentTab]);
    expect(screen.getByRole("menuitemradio", { name: copy.screenAudio })).toHaveAttribute("aria-checked", "true");
    expect(screen.getByRole("menuitemradio", { name: copy.currentTab })).toBeDisabled();
    fireEvent.click(screen.getByRole("menuitemradio", { name: copy.audioOnly }));
    expect(onChangeSource).toHaveBeenCalledWith("audio_only");
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
    expect(sourceButton()).toHaveFocus();
    view.rerender(<CaptureControls {...defaults} onChangeSource={onChangeSource} currentTabAvailable />);
    fireEvent.click(sourceButton());
    fireEvent.click(screen.getByRole("menuitemradio", { name: copy.currentTab }));
    expect(onChangeSource).toHaveBeenLastCalledWith("current-tab");
  });
  it("supports the keyboard: arrows open and move, Escape closes and returns focus", () => {
    render(<CaptureControls {...defaults} currentTabAvailable />);
    fireEvent.keyDown(sourceButton(), { key: "ArrowDown" });
    const items = screen.getAllByRole("menuitemradio");
    expect(items[0]).toHaveFocus();
    fireEvent.keyDown(screen.getByRole("menu"), { key: "ArrowDown" });
    expect(items[1]).toHaveFocus();
    fireEvent.keyDown(screen.getByRole("menu"), { key: "End" });
    expect(items[2]).toHaveFocus();
    fireEvent.keyDown(screen.getByRole("menu"), { key: "ArrowDown" });
    expect(items[0]).toHaveFocus();
    fireEvent.keyDown(screen.getByRole("menu"), { key: "Escape" });
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
    expect(sourceButton()).toHaveFocus();
  });
  it("closes the menu on an outside press", () => {
    render(<CaptureControls {...defaults} />);
    fireEvent.click(sourceButton());
    fireEvent.pointerDown(document.body);
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
  });
  it("toggles the microphone, which disables the device control with an explanation", () => {
    const onToggleMicrophone = vi.fn();
    const mic = { deviceId: "mic-test", label: "USB" };
    const view = render(<CaptureControls {...defaults} microphones={[mic]} selectedMicrophone={mic} onToggleMicrophone={onToggleMicrophone} />);
    expect(screen.getByRole("button", { name: copy.microphoneSelector })).toBeEnabled();
    fireEvent.click(screen.getByRole("switch", { name: copy.microphone }));
    expect(onToggleMicrophone).toHaveBeenCalledOnce();
    view.rerender(<CaptureControls {...defaults} microphones={[mic]} selectedMicrophone={mic} microphoneEnabled={false} />);
    const device = screen.getByRole("button", { name: copy.microphoneSelector });
    expect(device).toBeDisabled();
    expect(device).toHaveAttribute("title", copy.enableMicrophoneHint);
    expect(screen.getByRole("switch", { name: copy.microphone })).toHaveAttribute("aria-checked", "false");
  });
  it("chooses the input device from the menu", () => {
    const onSelectMicrophone = vi.fn();
    const mics = [{ deviceId: "mic-a", label: "Built-in" }, { deviceId: "mic-b", label: "USB" }];
    render(<CaptureControls {...defaults} microphones={mics} selectedMicrophone={mics[0]} onSelectMicrophone={onSelectMicrophone} />);
    fireEvent.click(screen.getByRole("button", { name: copy.microphoneSelector }));
    expect(screen.getByRole("menu", { name: copy.microphoneMenu })).toBeInTheDocument();
    expect(screen.getByRole("menuitemradio", { name: "Built-in" })).toHaveAttribute("aria-checked", "true");
    fireEvent.click(screen.getByRole("menuitemradio", { name: "USB" }));
    expect(onSelectMicrophone).toHaveBeenCalledWith(mics[1]);
  });
  it("opens the settings menu in place and starts from the primary button", () => {
    const onChangeSettings = vi.fn(), onToggleCapture = vi.fn();
    render(<CaptureControls {...defaults} onChangeSettings={onChangeSettings} onToggleCapture={onToggleCapture} />);
    fireEvent.click(screen.getByRole("button", { name: copy.settings }));
    expect(screen.getByRole("dialog", { name: copy.settings })).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText(copy.resolution), { target: { value: "1080p" } });
    expect(onChangeSettings).toHaveBeenCalledWith({ resolution: "1080p" });
    fireEvent.click(screen.getByRole("button", { name: copy.newRecording }));
    expect(onToggleCapture).toHaveBeenCalledOnce();
  });
  it("renders only actual source metadata and the timer while recording", () => {
    render(<CaptureControls {...defaults} captureState="recording" elapsedTimeMs={65000} tabTitle="Meet" recordedVideo recordedMicrophone="USB" />);
    expect(screen.getByText("01:05")).toBeInTheDocument();
    expect(screen.getByText(`${copy.tab} Meet`)).toBeInTheDocument();
    expect(screen.getByText(copy.tabVideo)).toBeInTheDocument();
    expect(screen.getByText("USB")).toBeInTheDocument();
    expect(screen.queryByRole("group", { name: copy.sourceMenu })).not.toBeInTheDocument();
  });
  it("does not claim unreported video or microphone sources", () => {
    render(<CaptureControls {...defaults} captureState="recording" />);
    expect(screen.queryByText(copy.tabVideo)).not.toBeInTheDocument();
    expect(screen.getByLabelText(copy.recordingSources).children).toHaveLength(1);
  });
  it("disables every start control while selecting and shows a localized error", () => {
    render(<CaptureControls {...defaults} selecting currentTabAvailable startError={copy.startError} />);
    expect(screen.getByRole("button", { name: copy.newRecording })).toBeDisabled();
    expect(sourceButton()).toBeDisabled();
    expect(screen.getByRole("switch", { name: copy.microphone })).toBeDisabled();
    expect(screen.getByRole("alert")).toHaveTextContent(copy.startError);
  });
  it("blocks the primary button and explains it when the selected tab cannot be recorded", () => {
    render(<CaptureControls {...defaults} source="current-tab" />);
    expect(sourceButton()).toHaveTextContent(copy.currentTab);
    expect(screen.getByRole("button", { name: copy.newRecording })).toBeDisabled();
    expect(screen.getByRole("note")).toHaveTextContent(copy.tabUnavailable);
  });
  it("tells the user the tab has no on-page controls only when it cannot host them", () => {
    const { rerender } = render(<CaptureControls {...defaults} captureState="recording" />);
    expect(screen.queryByText(copy.noOverlay)).not.toBeInTheDocument();
    rerender(<CaptureControls {...defaults} captureState="recording" overlayUnavailable />);
    expect(screen.getByText(copy.noOverlay)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: copy.stop })).toBeEnabled();
  });
});
