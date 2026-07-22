// Example-based test: Capture_Controls (Req. 3.1, 3.2, 3.7, 3.8, 3.9, 3.10)
import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { CaptureControls } from "./CaptureControls";

describe("CaptureControls", () => {
  it("offers 'Screen + audio' in the Audio_Source_Selector (Req. 3.1, 3.2)", () => {
    render(
      <CaptureControls
        captureState="idle"
        microphones={[]}
        onToggleCapture={() => {}}
        onOpenSettings={() => {}}
        elapsedTimeMs={0}
      />
    );
    expect(screen.getByText("Screen + audio")).toBeInTheDocument();
  });

  it("shows an empty state when no microphones are available, without blocking the rest (Req. 3.7)", () => {
    render(
      <CaptureControls
        captureState="idle"
        microphones={[]}
        onToggleCapture={() => {}}
        onOpenSettings={() => {}}
        elapsedTimeMs={0}
      />
    );
    expect(screen.getByText(/no microphones/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /settings/i })).toBeEnabled();
  });

  it("shows the Settings_Button and fires onOpenSettings (Req. 3.8)", () => {
    const onOpenSettings = vi.fn();
    render(
      <CaptureControls
        captureState="idle"
        microphones={[]}
        onToggleCapture={() => {}}
        onOpenSettings={onOpenSettings}
        elapsedTimeMs={0}
      />
    );
    screen.getByRole("button", { name: /settings/i }).click();
    expect(onOpenSettings).toHaveBeenCalledTimes(1);
  });

  it("shows the 'MM:SS' stopwatch while recording (Req. 3.9)", () => {
    render(
      <CaptureControls
        captureState="recording"
        microphones={[]}
        onToggleCapture={() => {}}
        onOpenSettings={() => {}}
        elapsedTimeMs={65_000}
      />
    );
    expect(screen.getByText("01:05")).toBeInTheDocument();
  });

  it("shows an error if starting the capture fails (Req. 3.10)", () => {
    render(
      <CaptureControls
        captureState="idle"
        microphones={[]}
        onToggleCapture={() => {}}
        onOpenSettings={() => {}}
        elapsedTimeMs={0}
        startError="Capture could not be started"
      />
    );
    expect(screen.getByText("Capture could not be started")).toBeInTheDocument();
  });
});
