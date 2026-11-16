import { describe, it, expect, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { CaptureControls, type CaptureControlsProps } from "./CaptureControls";
import { panelCopy as copy } from "../copy";
const defaults: CaptureControlsProps = { captureState: "idle", microphones: [], onToggleCapture: vi.fn(), elapsedTimeMs: 0 };

describe("CaptureControls", () => {
  it("renders the approved start controls and an empty microphone selector", () => {
    render(<CaptureControls {...defaults} />);
    expect(screen.getByRole("heading", { name: copy.heading })).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: copy.screenAudio })).toHaveAttribute("aria-checked", "true");
    expect(screen.getByRole("radio", { name: copy.audioOnly })).toHaveAttribute("aria-checked", "false");
    expect(screen.getByLabelText(copy.microphoneSelector)).toBeDisabled();
    expect(screen.getByText(copy.noMicrophones)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: copy.record })).toBeEnabled();
  });
  it("sends mode, microphone and current-tab actions", () => {
    const onChangeMode = vi.fn(), onToggleMicrophone = vi.fn(), onCaptureCurrentTab = vi.fn(), onSelectMicrophone = vi.fn();
    const mic = { deviceId: "mic-test", label: "USB" };
    render(<CaptureControls {...defaults} microphones={[mic]} onSelectMicrophone={onSelectMicrophone} onChangeMode={onChangeMode} onToggleMicrophone={onToggleMicrophone} onCaptureCurrentTab={onCaptureCurrentTab} currentTabAvailable />);
    fireEvent.click(screen.getByRole("radio", { name: copy.audioOnly }));
    expect(onChangeMode).toHaveBeenCalledWith("audio_only");
    fireEvent.click(screen.getByRole("switch", { name: copy.microphone }));
    expect(onToggleMicrophone).toHaveBeenCalledOnce();
    fireEvent.change(screen.getByLabelText(copy.microphoneSelector), { target: { value: mic.deviceId } });
    expect(onSelectMicrophone).toHaveBeenCalledWith(mic);
    fireEvent.click(screen.getByRole("button", { name: copy.recordTab }));
    expect(onCaptureCurrentTab).toHaveBeenCalledOnce();
  });
  it("renders only actual source metadata and the timer while recording", () => {
    render(<CaptureControls {...defaults} captureState="recording" elapsedTimeMs={65000} tabTitle="Meet" recordedVideo recordedMicrophone="USB" />);
    expect(screen.getByText("01:05")).toBeInTheDocument();
    expect(screen.getByText(`${copy.tab} Meet`)).toBeInTheDocument();
    expect(screen.getByText(copy.tabVideo)).toBeInTheDocument();
    expect(screen.getByText("USB")).toBeInTheDocument();
    expect(screen.queryByRole("radiogroup")).not.toBeInTheDocument();
  });
  it("does not claim unreported video or microphone sources", () => {
    render(<CaptureControls {...defaults} captureState="recording" />);
    expect(screen.queryByText(copy.tabVideo)).not.toBeInTheDocument();
    expect(screen.getByLabelText(copy.recordingSources).children).toHaveLength(1);
  });
  it("disables both starts while selecting and shows a localized error", () => {
    render(<CaptureControls {...defaults} selecting currentTabAvailable startError={copy.startError} />);
    expect(screen.getByRole("button", { name: copy.record })).toBeDisabled();
    expect(screen.getByRole("button", { name: copy.recordTab })).toBeDisabled();
    expect(screen.getByRole("alert")).toHaveTextContent(copy.startError);
  });
  it("tells the user the tab has no on-page controls only when it cannot host them", () => {
    const { rerender } = render(<CaptureControls {...defaults} captureState="recording" />);
    expect(screen.queryByText(copy.noOverlay)).not.toBeInTheDocument();
    rerender(<CaptureControls {...defaults} captureState="recording" overlayUnavailable />);
    expect(screen.getByText(copy.noOverlay)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: copy.stop })).toBeEnabled();
  });
});
