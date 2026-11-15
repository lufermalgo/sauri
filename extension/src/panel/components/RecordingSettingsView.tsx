import React from "react";
import type { RecordingSettings } from "../../core/types";
import { panelCopy as copy } from "../copy";

export function RecordingSettingsView({ settings, onChange, onBack, pending, error }: {
  settings: RecordingSettings;
  onChange: (change: Partial<RecordingSettings>) => void;
  onBack: () => void;
  pending: boolean;
  error: string | null;
}) {
  return <section className="panel-stack">
    <button className="panel-back" onClick={onBack}>{copy.back}</button>
    <h1>{copy.settingsTitle}</h1>
    <div className="panel-card panel-stack">
      <label className="panel-stack">{copy.countdown}<select disabled={pending} value={settings.countdownSeconds} onChange={event => onChange({ countdownSeconds: Number(event.target.value) as RecordingSettings["countdownSeconds"] })}>{[0,3,5,10].map(seconds => <option key={seconds} value={seconds}>{seconds} s</option>)}</select></label>
      <label className="panel-row"><input type="checkbox" checked={settings.showControlBar} disabled={pending} onChange={event => onChange({ showControlBar: event.target.checked })} />{copy.controlBar}</label>
    </div>
    {error && <p role="alert">{error}</p>}
  </section>;
}
