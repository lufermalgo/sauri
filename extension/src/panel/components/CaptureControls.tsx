import React from "react";
import { AppWindow, AudioLines, Check, Monitor, Pause, Play, Square } from "lucide-react";
import { Icon } from "../../core/design/Icon";
import { formatTimestamp } from "../../core/time";
import type { CaptureState } from "../../core/types";
import { panelCopy as copy } from "../copy";

export interface MicOption { deviceId: string | null; label: string }
export interface CaptureControlsProps {
  captureState: CaptureState;
  microphones: MicOption[];
  selectedMicrophone?: MicOption;
  onSelectMicrophone?: (mic: MicOption) => void;
  microphoneEnabled?: boolean;
  onToggleMicrophone?: () => void;
  captureMode?: "screen_audio" | "audio_only";
  onChangeMode?: (mode: "screen_audio" | "audio_only") => void;
  onToggleCapture: () => void;
  onCaptureCurrentTab?: () => void;
  currentTabAvailable?: boolean;
  onPause?: () => void;
  onCancel?: () => void;
  paused?: boolean;
  tabTitle?: string;
  recordedMicrophone?: string;
  recordedVideo?: boolean;
  commandPending?: boolean;
  elapsedTimeMs?: number;
  startError?: string | null;
  selecting?: boolean;
  microphoneError?: string | null;
}

export function CaptureControls({ captureState, microphones, selectedMicrophone, onSelectMicrophone,
  microphoneEnabled = true, onToggleMicrophone, captureMode = "screen_audio", onChangeMode,
  onToggleCapture, onCaptureCurrentTab, currentTabAvailable, onPause, onCancel,
  paused, tabTitle, recordedMicrophone, recordedVideo, commandPending, elapsedTimeMs, startError, selecting, microphoneError,
}: CaptureControlsProps) {
  if (captureState === "recording" || captureState === "stopping") return <section className="panel-stack panel-recording">
    <div className="panel-card panel-clock" aria-label={copy.timer}>
      <span className="panel-stopwatch">{elapsedTimeMs === undefined ? "--:--" : formatTimestamp(elapsedTimeMs)}</span>
      {tabTitle && <span>{copy.tab} {tabTitle}</span>}
      {/* Decorative activity animation, not a measured audio level. */}
      <div className={`panel-activity ${paused ? "panel-activity-paused" : ""}`} aria-hidden="true">
        {[8,14,22,12,28,18,10,30,20,12,24,16,8,26,14,20,10,18,12,8].map((height, index) => <span key={index} style={{ height, animationDelay: `${index * 0.07}s` }} />)}
      </div>
    </div>
    <div className="panel-row panel-actions">
      <button className="panel-with-icon" disabled={commandPending || captureState === "stopping"} onClick={onPause}><Icon icon={paused ? Play : Pause} />{paused ? copy.resume : copy.pause}</button>
      <button className="panel-primary panel-with-icon" disabled={commandPending || captureState === "stopping"} onClick={onToggleCapture}><Icon icon={Square} size={16} />{captureState === "stopping" ? copy.stopping : copy.stop}</button>
    </div>
    <ul className="panel-sources" aria-label={copy.recordingSources}>
      <li><Icon icon={Check} size={14} strokeWidth={2.5} className="panel-check" />{copy.tabAudio}</li>
      {recordedVideo && <li><Icon icon={Check} size={14} strokeWidth={2.5} className="panel-check" />{copy.tabVideo}</li>}
      {recordedMicrophone && <li><Icon icon={Check} size={14} strokeWidth={2.5} className="panel-check" />{recordedMicrophone}</li>}
    </ul>
    <p>{copy.recordingHelp}</p>
    {startError && <p role="alert">{startError}</p>}
    <button className="panel-danger-link" disabled={commandPending || captureState === "stopping"} onClick={onCancel}>{copy.discard}</button>
  </section>;

  return <section className="panel-stack">
    <div><h1>{copy.heading}</h1><p>{copy.introduction}</p></div>
    <section className="panel-card panel-stack" aria-label={copy.capture}>
      <div className="panel-segmented" role="radiogroup" aria-label={copy.captureMode}>
        {(["screen_audio", "audio_only"] as const).map(mode => <button key={mode} role="radio" aria-checked={captureMode === mode} disabled={selecting} onClick={() => onChangeMode?.(mode)}><Icon icon={mode === "screen_audio" ? Monitor : AudioLines} size={16} />{mode === "screen_audio" ? copy.screenAudio : copy.audioOnly}</button>)}
      </div>
      <div className="panel-row">
        <button className="panel-switch" role="switch" aria-checked={microphoneEnabled} aria-label={copy.microphone} disabled={selecting} onClick={onToggleMicrophone}><span /></button>
        <label className="panel-mic-label">{copy.microphone}
          <select aria-label={copy.microphoneSelector} disabled={!microphoneEnabled || selecting || microphones.length === 0} value={selectedMicrophone?.deviceId ?? ""} onChange={event => {
            const mic = microphones.find(item => item.deviceId === event.target.value);
            if (mic) onSelectMicrophone?.(mic);
          }}>
            {microphones.length === 0 && <option value="">{copy.noMicrophones}</option>}
            {microphones.map(mic => <option key={mic.deviceId ?? "none"} value={mic.deviceId ?? ""}>{mic.label}</option>)}
          </select>
        </label>
      </div>
      <p className="panel-small">{copy.microphoneHelp}</p>
      {microphoneError && <p role="alert">{microphoneError}</p>}
    </section>
    <div className="panel-stack panel-start">
      <button className="panel-primary panel-record-button panel-with-icon" disabled={selecting} onClick={onToggleCapture}><span className="panel-dot" aria-hidden="true" />{copy.record}</button>
      <p className="panel-small panel-center">{copy.pickerHelp}</p>
      <button className="panel-with-icon" disabled={!currentTabAvailable || selecting} onClick={onCaptureCurrentTab}><Icon icon={AppWindow} size={16} />{copy.recordTab}</button>
    </div>
    {startError && <p role="alert">{startError}</p>}
  </section>;
}
