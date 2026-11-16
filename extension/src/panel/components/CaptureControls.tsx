import React from "react";
import { AppWindow, AudioLines, Check, Mic, Monitor, Pause, Play, Plus, Square } from "lucide-react";
import { Icon } from "../../core/design/Icon";
import { formatTimestamp } from "../../core/time";
import type { CaptureState, RecordingSettings } from "../../core/types";
import { useT } from "../../i18n";
import { DEFAULT_RECORDING_SETTINGS } from "../recordingSettings";
import { MenuButton, type MenuOption } from "./MenuButton";
import { SettingsMenu } from "./SettingsMenu";

export type CaptureSourceChoice = "screen_audio" | "audio_only" | "current-tab";
const SOURCE_ICONS = { screen_audio: Monitor, audio_only: AudioLines, "current-tab": AppWindow } as const;

export interface MicOption { deviceId: string | null; label: string }
export interface CaptureControlsProps {
  captureState: CaptureState;
  microphones: MicOption[];
  selectedMicrophone?: MicOption;
  onSelectMicrophone?: (mic: MicOption) => void;
  microphoneEnabled?: boolean;
  onToggleMicrophone?: () => void;
  source?: CaptureSourceChoice;
  onChangeSource?: (source: CaptureSourceChoice) => void;
  onToggleCapture: () => void;
  settings?: RecordingSettings;
  onChangeSettings?: (change: Partial<RecordingSettings>) => void;
  settingsDisabled?: boolean;
  settingsError?: string | null;
  currentTabAvailable?: boolean;
  onPause?: () => void;
  onCancel?: () => void;
  paused?: boolean;
  tabTitle?: string;
  overlayUnavailable?: boolean;
  recordedMicrophone?: string;
  recordedVideo?: boolean;
  commandPending?: boolean;
  elapsedTimeMs?: number;
  startError?: string | null;
  selecting?: boolean;
  microphoneError?: string | null;
}

export function CaptureControls({ captureState, microphones, selectedMicrophone, onSelectMicrophone,
  microphoneEnabled = true, onToggleMicrophone, source = "screen_audio", onChangeSource,
  onToggleCapture, settings = DEFAULT_RECORDING_SETTINGS, onChangeSettings, settingsDisabled, settingsError, currentTabAvailable, onPause, onCancel,
  paused, tabTitle, overlayUnavailable, recordedMicrophone, recordedVideo, commandPending, elapsedTimeMs, startError, selecting, microphoneError,
}: CaptureControlsProps) {
  const { t } = useT();
  const SOURCE_LABELS: Record<CaptureSourceChoice, string> = { screen_audio: t("panel:screenAudio"), audio_only: t("panel:audioOnly"), "current-tab": t("panel:currentTab") };
  const settingsMenu = (recording: boolean) => <SettingsMenu settings={settings} onChange={change => onChangeSettings?.(change)} disabled={settingsDisabled} recording={recording} error={settingsError} />;

  if (captureState === "recording" || captureState === "stopping") return <section className="panel-stack panel-recording">
    <div className="panel-controls panel-recording-tools">{settingsMenu(true)}</div>
    <div className="panel-card panel-clock" aria-label={t("panel:timer")}>
      <span className="panel-stopwatch">{elapsedTimeMs === undefined ? "--:--" : formatTimestamp(elapsedTimeMs)}</span>
      {tabTitle && <span>{t("panel:tab")} {tabTitle}</span>}
      {/* Decorative activity animation, not a measured audio level. */}
      <div className={`panel-activity ${paused ? "panel-activity-paused" : ""}`} aria-hidden="true">
        {[8,14,22,12,28,18,10,30,20,12,24,16,8,26,14,20,10,18,12,8].map((height, index) => <span key={index} style={{ height, animationDelay: `${index * 0.07}s` }} />)}
      </div>
    </div>
    <div className="panel-row panel-actions">
      <button className="panel-with-icon" disabled={commandPending || captureState === "stopping"} onClick={onPause}><Icon icon={paused ? Play : Pause} />{paused ? t("panel:resume") : t("panel:pause")}</button>
      <button className="panel-primary panel-with-icon" disabled={commandPending || captureState === "stopping"} onClick={onToggleCapture}><Icon icon={Square} size={16} />{captureState === "stopping" ? t("panel:stopping") : t("panel:stop")}</button>
    </div>
    <ul className="panel-sources" aria-label={t("panel:recordingSources")}>
      <li><Icon icon={Check} size={14} strokeWidth={2.5} className="panel-check" />{t("panel:tabAudio")}</li>
      {recordedVideo && <li><Icon icon={Check} size={14} strokeWidth={2.5} className="panel-check" />{t("panel:tabVideo")}</li>}
      {recordedMicrophone && <li><Icon icon={Check} size={14} strokeWidth={2.5} className="panel-check" />{recordedMicrophone}</li>}
    </ul>
    {overlayUnavailable && <p role="note">{t("panel:noOverlay")}</p>}
    <p>{t("panel:recordingHelp")}</p>
    {startError && <p role="alert">{startError}</p>}
    <button className="panel-danger-link" disabled={commandPending || captureState === "stopping"} onClick={onCancel}>{t("panel:discard")}</button>
  </section>;

  const sourceOptions: MenuOption<CaptureSourceChoice>[] = (["screen_audio", "audio_only", "current-tab"] as const).map(value => ({
    value, label: SOURCE_LABELS[value], icon: SOURCE_ICONS[value],
    ...(value === "current-tab" && !currentTabAvailable ? { disabled: true, title: t("panel:tabUnavailable") } : {}),
  }));
  const microphoneOptions: MenuOption<string>[] = microphones.map(mic => ({ value: mic.deviceId ?? "", label: mic.label }));
  const tabBlocked = source === "current-tab" && !currentTabAvailable;
  const micMenuDisabled = !microphoneEnabled || selecting || microphones.length === 0;

  return <section className="panel-stack">
    <div className="panel-controls">
      <div className="panel-control-group panel-source-group" role="group" aria-label={t("panel:sourceMenu")}>
        <MenuButton className="panel-control-trigger" options={sourceOptions} value={source} menuLabel={t("panel:sourceMenu")} disabled={selecting} onSelect={value => onChangeSource?.(value)}>
          <Icon icon={SOURCE_ICONS[source]} size={16} /><span className="panel-ellipsis">{SOURCE_LABELS[source]}</span>
        </MenuButton>
        <button type="button" className="panel-switch" role="switch" aria-checked={microphoneEnabled} aria-label={t("panel:microphone")} title={t("panel:microphone")} disabled={selecting} onClick={onToggleMicrophone}><span /></button>
      </div>
      <div className="panel-control-group">
        <MenuButton className="panel-control-trigger panel-mic-trigger" options={microphoneOptions} value={selectedMicrophone?.deviceId ?? undefined} menuLabel={t("panel:microphoneMenu")}
          triggerLabel={t("panel:microphoneSelector")} title={!microphoneEnabled ? t("panel:enableMicrophoneHint") : microphones.length === 0 ? t("panel:noMicrophones") : t("panel:microphoneSelector")} disabled={micMenuDisabled}
          onSelect={value => { const mic = microphones.find(item => (item.deviceId ?? "") === value); if (mic) onSelectMicrophone?.(mic); }}>
          <Icon icon={Mic} size={16} />
        </MenuButton>
      </div>
      {settingsMenu(false)}
    </div>
    {microphoneError && <p role="alert">{microphoneError}</p>}
    <button type="button" className="panel-primary panel-new-recording panel-with-icon" disabled={selecting || tabBlocked} onClick={onToggleCapture}><Icon icon={Plus} size={18} />{t("panel:newRecording")}</button>
    {tabBlocked && <p className="panel-small" role="note">{t("panel:tabUnavailable")}</p>}
    {startError && <p role="alert">{startError}</p>}
  </section>;
}
