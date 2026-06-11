import React, { useEffect, useState, useRef, useCallback } from "react";

interface SauriState {
  status: "idle" | "pending" | "recording";
  meetingUrl?: string;
  meetingTitle?: string;
}

interface MicOption {
  deviceId: string | null;
  label: string;
}

interface Resolution {
  label: string;
  width: number;
  height: number;
}

const RESOLUTIONS: Resolution[] = [
  { label: "480p", width: 854, height: 480 },
  { label: "720p", width: 1280, height: 720 },
  { label: "1080p", width: 1920, height: 1080 },
];

interface CountdownOption {
  label: string;
  seconds: number;
}

const COUNTDOWN_OPTIONS: CountdownOption[] = [
  { label: "Sin cuenta regresiva", seconds: 0 },
  { label: "3 segundos", seconds: 3 },
  { label: "5 segundos", seconds: 5 },
];

type CaptureMode = "screen_audio" | "audio_only";

interface CaptureModeOption {
  label: string;
  value: CaptureMode;
}

const CAPTURE_MODES: CaptureModeOption[] = [
  { label: "Pantalla + audio", value: "screen_audio" },
  { label: "Solo audio", value: "audio_only" },
];

const DEFAULT_STATE: SauriState = { status: "idle" };

export function App() {
  const [state, setState] = useState<SauriState>(DEFAULT_STATE);
  const [resolution, setResolution] = useState<Resolution>(RESOLUTIONS[1]); // 720p default
  const [countdownOption, setCountdownOption] = useState<CountdownOption>(COUNTDOWN_OPTIONS[1]); // 3s default
  const [countdownValue, setCountdownValue] = useState<number | null>(null);
  const [captureMode, setCaptureMode] = useState<CaptureModeOption>(CAPTURE_MODES[0]); // screen_audio default
  const [micOptions, setMicOptions] = useState<MicOption[]>([{ deviceId: null, label: "Sin micrófono" }]);
  const [selectedMic, setSelectedMic] = useState<MicOption>({ deviceId: null, label: "Sin micrófono" });
  const countdownTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    chrome.storage.session.get("sauriState").then((result) => {
      if (result.sauriState) {
        setState(result.sauriState as SauriState);
      }
    });

    const listener = (
      changes: { [key: string]: chrome.storage.StorageChange },
      areaName: string
    ) => {
      if (areaName === "session" && changes.sauriState) {
        setState(
          (changes.sauriState.newValue as SauriState) ?? DEFAULT_STATE
        );
      }
    };

    chrome.storage.onChanged.addListener(listener);
    return () => {
      chrome.storage.onChanged.removeListener(listener);
      if (countdownTimerRef.current) {
        clearInterval(countdownTimerRef.current);
      }
    };
  }, []);

  // Enumerate audio input devices on mount
  useEffect(() => {
    async function enumerateMics() {
      try {
        const devices = await navigator.mediaDevices.enumerateDevices();
        const audioInputs = devices.filter((d) => d.kind === "audioinput");
        const options: MicOption[] = [{ deviceId: null, label: "Sin micrófono" }];
        audioInputs.forEach((device, index) => {
          options.push({
            deviceId: device.deviceId,
            label: device.label || `Microphone ${index + 1}`,
          });
        });
        setMicOptions(options);
      } catch (err) {
        console.warn("[sauri] Could not enumerate audio devices:", err);
      }
    }
    enumerateMics();
  }, []);

  const startCapture = useCallback(() => {
    chrome.runtime.sendMessage({
      type: "start-capture",
      resolution: { width: resolution.width, height: resolution.height },
      micDeviceId: selectedMic.deviceId,
    });
  }, [resolution, selectedMic]);

  const handleStartCapture = () => {
    if (countdownOption.seconds === 0) {
      startCapture();
      return;
    }

    // Start countdown
    setCountdownValue(countdownOption.seconds);
    let remaining = countdownOption.seconds;

    countdownTimerRef.current = setInterval(() => {
      remaining -= 1;
      if (remaining <= 0) {
        if (countdownTimerRef.current) {
          clearInterval(countdownTimerRef.current);
          countdownTimerRef.current = null;
        }
        setCountdownValue(null);
        startCapture();
      } else {
        setCountdownValue(remaining);
      }
    }, 1000);
  };

  const handleStopCapture = () => {
    chrome.runtime.sendMessage({ type: "stop-capture" });
  };

  const handleResolutionChange = (e: React.ChangeEvent<HTMLSelectElement>) => {
    const selected = RESOLUTIONS.find((r) => r.label === e.target.value);
    if (selected) setResolution(selected);
  };

  const handleCountdownChange = (e: React.ChangeEvent<HTMLSelectElement>) => {
    const selected = COUNTDOWN_OPTIONS.find((c) => c.label === e.target.value);
    if (selected) setCountdownOption(selected);
  };

  const handleCaptureModeChange = (e: React.ChangeEvent<HTMLSelectElement>) => {
    const selected = CAPTURE_MODES.find((m) => m.value === e.target.value);
    if (selected) {
      setCaptureMode(selected);
      chrome.runtime.sendMessage({ type: "set-capture-mode", captureMode: selected.value });
    }
  };

  const handleMicChange = (e: React.ChangeEvent<HTMLSelectElement>) => {
    const value = e.target.value;
    const selected = micOptions.find((m) => (m.deviceId ?? "") === value);
    if (selected) setSelectedMic(selected);
  };

  const selectStyle: React.CSSProperties = {
    padding: "0.25rem 0.5rem",
    borderRadius: "4px",
    border: "1px solid #ddd",
    fontSize: "0.8rem",
    flex: 1,
  };

  const labelStyle: React.CSSProperties = {
    fontSize: "0.75rem",
    color: "#555",
    marginBottom: "0.15rem",
  };

  return (
    <main style={{ padding: "1rem", fontFamily: "system-ui, sans-serif" }}>
      <h1 style={{ fontSize: "1.25rem", marginBottom: "0.5rem" }}>sauri</h1>

      {state.status === "idle" && (
        <p style={{ color: "#666" }}>Esperando reunión...</p>
      )}

      {state.status === "pending" && (
        <>
          <p style={{ color: "#1a73e8" }}>
            Reunión detectada: {state.meetingTitle ?? "Google Meet"}
          </p>

          {/* Settings area */}
          <div
            style={{
              display: "flex",
              gap: "0.5rem",
              marginTop: "0.5rem",
              marginBottom: "0.5rem",
            }}
          >
            <div style={{ display: "flex", flexDirection: "column", flex: 1 }}>
              <label style={labelStyle}>Resolución</label>
              <select
                value={resolution.label}
                onChange={handleResolutionChange}
                style={selectStyle}
              >
                {RESOLUTIONS.map((r) => (
                  <option key={r.label} value={r.label}>
                    {r.label}
                  </option>
                ))}
              </select>
            </div>
            <div style={{ display: "flex", flexDirection: "column", flex: 1 }}>
              <label style={labelStyle}>Cuenta regresiva</label>
              <select
                value={countdownOption.label}
                onChange={handleCountdownChange}
                style={selectStyle}
              >
                {COUNTDOWN_OPTIONS.map((c) => (
                  <option key={c.label} value={c.label}>
                    {c.label}
                  </option>
                ))}
              </select>
            </div>
          </div>

          {/* Capture mode selector */}
          <div style={{ marginBottom: "0.5rem" }}>
            <div style={{ display: "flex", flexDirection: "column" }}>
              <label style={labelStyle}>Modo de captura</label>
              <select
                value={captureMode.value}
                onChange={handleCaptureModeChange}
                style={selectStyle}
              >
                {CAPTURE_MODES.map((m) => (
                  <option key={m.value} value={m.value}>
                    {m.label}
                  </option>
                ))}
              </select>
            </div>
          </div>

          {/* Microphone selector */}
          <div style={{ marginBottom: "0.5rem" }}>
            <div style={{ display: "flex", flexDirection: "column" }}>
              <label style={labelStyle}>Micrófono</label>
              <select
                value={selectedMic.deviceId ?? ""}
                onChange={handleMicChange}
                style={selectStyle}
              >
                {micOptions.map((m) => (
                  <option key={m.deviceId ?? "none"} value={m.deviceId ?? ""}>
                    {m.label}
                  </option>
                ))}
              </select>
            </div>
          </div>

          {/* Countdown overlay */}
          {countdownValue !== null && (
            <div
              style={{
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                padding: "1rem",
                marginBottom: "0.5rem",
                backgroundColor: "rgba(26, 115, 232, 0.1)",
                borderRadius: "8px",
              }}
            >
              <span
                style={{
                  fontSize: "2rem",
                  fontWeight: "bold",
                  color: "#1a73e8",
                }}
              >
                {countdownValue}
              </span>
            </div>
          )}

          <button
            onClick={handleStartCapture}
            disabled={countdownValue !== null}
            style={{
              padding: "0.5rem 1rem",
              backgroundColor: countdownValue !== null ? "#999" : "#1a73e8",
              color: "white",
              border: "none",
              borderRadius: "4px",
              cursor: countdownValue !== null ? "not-allowed" : "pointer",
            }}
          >
            Grabar
          </button>
        </>
      )}

      {state.status === "recording" && (
        <>
          <p style={{ color: "#d93025", fontWeight: "bold" }}>
            🔴 Grabando...
          </p>
          <button
            onClick={handleStopCapture}
            style={{
              marginTop: "0.5rem",
              padding: "0.5rem 1rem",
              backgroundColor: "#d93025",
              color: "white",
              border: "none",
              borderRadius: "4px",
              cursor: "pointer",
            }}
          >
            Detener
          </button>
        </>
      )}
    </main>
  );
}
