// Capture_Controls — Req. 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 3.8, 3.9, 3.10
import React from "react";
import { formatTimestamp } from "../../core/time";
import type { CaptureState } from "../../core/types";
import { COLOR_TOKENS, SPACING_TOKENS, TYPOGRAPHY_TOKENS, RADIUS_TOKENS } from "../../core/design/tokens";

export interface MicOption {
  deviceId: string | null;
  label: string;
}

export interface CaptureControlsProps {
  captureState: CaptureState;
  microphones: MicOption[];
  selectedMicrophone?: MicOption;
  onSelectMicrophone?: (mic: MicOption) => void;
  onToggleCapture: () => void;
  onOpenSettings: () => void;
  elapsedTimeMs: number;
  startError?: string | null;
  microphoneError?: string | null;
}

const AUDIO_SOURCES = ["Screen + audio"];

/** Converts the running recording stopwatch to "MM:SS" (Req. 3.9), reusing formatTimestamp. */
function formatStopwatch(elapsedTimeMs: number): string {
  return formatTimestamp(elapsedTimeMs);
}

export function CaptureControls({
  captureState,
  microphones,
  selectedMicrophone,
  onSelectMicrophone,
  onToggleCapture,
  onOpenSettings,
  elapsedTimeMs,
  startError,
  microphoneError,
}: CaptureControlsProps) {
  const recording = captureState === "recording";

  return (
    <section
      style={{
        display: "flex",
        flexDirection: "column",
        gap: SPACING_TOKENS.space2,
        padding: `0 ${SPACING_TOKENS.space4}`,
      }}
    >
      <div style={{ display: "flex", flexDirection: "column" }}>
        <label style={{ fontSize: TYPOGRAPHY_TOKENS.textSm }}>Audio source</label>
        <select defaultValue={AUDIO_SOURCES[0]} aria-label="Audio source selector">
          {AUDIO_SOURCES.map((f) => (
            <option key={f} value={f}>
              {f}
            </option>
          ))}
        </select>
      </div>

      <div style={{ display: "flex", flexDirection: "column" }}>
        <label style={{ fontSize: TYPOGRAPHY_TOKENS.textSm }}>Microphone</label>
        {microphones.length === 0 ? (
          <p
            role={microphoneError ? "alert" : undefined}
            style={{
              color: microphoneError ? COLOR_TOKENS.error : COLOR_TOKENS.textMuted,
              fontSize: TYPOGRAPHY_TOKENS.textSm,
              margin: 0,
            }}
          >
            {microphoneError ?? "No microphones available"}
          </p>
        ) : (
          <select
            aria-label="Microphone selector"
            value={selectedMicrophone?.deviceId ?? ""}
            onChange={(e) => {
              const selection = microphones.find((m) => (m.deviceId ?? "") === e.target.value);
              if (selection && onSelectMicrophone) onSelectMicrophone(selection);
            }}
          >
            {microphones.map((m) => (
              <option key={m.deviceId ?? "none"} value={m.deviceId ?? ""}>
                {m.label}
              </option>
            ))}
          </select>
        )}
      </div>

      <div style={{ display: "flex", alignItems: "center", gap: SPACING_TOKENS.space2 }}>
        <button
          type="button"
          role="switch"
          aria-checked={recording}
          onClick={onToggleCapture}
          disabled={captureState === "stopping"}
          style={{
            backgroundColor: recording ? COLOR_TOKENS.recording : COLOR_TOKENS.surfaceAlt,
            color: COLOR_TOKENS.text,
            border: "none",
            borderRadius: RADIUS_TOKENS.radiusMd,
            padding: `${SPACING_TOKENS.space2} ${SPACING_TOKENS.space3}`,
            cursor: "pointer",
          }}
        >
          {recording ? "Stop" : "Record"}
        </button>

        {recording && (
          <span
            aria-live="polite"
            style={{ display: "flex", alignItems: "center", gap: "4px", color: COLOR_TOKENS.recording, fontWeight: TYPOGRAPHY_TOKENS.weightSemibold }}
          >
            <span aria-hidden="true">●</span>
            <span>{formatStopwatch(elapsedTimeMs)}</span>
          </span>
        )}

        <button
          type="button"
          onClick={onOpenSettings}
          style={{
            marginLeft: "auto",
            background: "none",
            border: `1px solid ${COLOR_TOKENS.textMuted}`,
            borderRadius: RADIUS_TOKENS.radiusSm,
            color: COLOR_TOKENS.text,
            padding: `${SPACING_TOKENS.space1} ${SPACING_TOKENS.space2}`,
            cursor: "pointer",
          }}
        >
          Settings
        </button>
      </div>

      {startError && (
        <p role="alert" style={{ color: COLOR_TOKENS.error, fontSize: TYPOGRAPHY_TOKENS.textSm, margin: 0 }}>
          {startError}
        </p>
      )}
    </section>
  );
}
