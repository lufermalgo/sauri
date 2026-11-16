import React, { useEffect, useId, useRef, useState } from "react";
import { MicOff, MonitorPlay, PanelBottom, SlidersHorizontal, Timer, type LucideIcon } from "lucide-react";
import { Icon } from "../../core/design/Icon";
import { RESOLUTIONS } from "../../core/resolution";
import type { RecordingResolution, RecordingSettings } from "../../core/types";
import { useT } from "../../i18n";

const COUNTDOWN_OPTIONS = [0, 3, 5, 10] as const;

function Row({ icon, children }: { icon: LucideIcon; children: React.ReactNode }) {
  return <div className="panel-settings-row"><Icon icon={icon} size={16} />{children}</div>;
}

function SwitchRow({ icon, label, checked, onToggle, title }: { icon: LucideIcon; label: string; checked: boolean; onToggle: () => void; title?: string }) {
  return <button type="button" role="switch" aria-checked={checked} className="panel-settings-row panel-settings-switch-row" title={title} onClick={onToggle}>
    <Icon icon={icon} size={16} /><span className="panel-settings-label">{label}</span><span className="panel-settings-track" aria-hidden="true"><span /></span>
  </button>;
}

export interface SettingsMenuProps {
  settings: RecordingSettings;
  onChange: (change: Partial<RecordingSettings>) => void;
  /** Settings not loaded yet, or a recording is starting. */
  disabled?: boolean;
  /** Countdown and resolution only apply to the next recording, so they are locked meanwhile. */
  recording?: boolean;
  error?: string | null;
}

/** Non-modal popover under the settings button. Every change is saved as soon as it is made. */
export function SettingsMenu({ settings, onChange, disabled, recording, error }: SettingsMenuProps) {
  const { t } = useT();
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLSpanElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const popoverId = useId();
  const countdownId = useId();
  const resolutionId = useId();
  const hintId = useId();

  useEffect(() => {
    if (!open) return;
    rootRef.current?.querySelector<HTMLElement>("select:not(:disabled), button[role='switch']")?.focus();
    const close = (event: PointerEvent) => { if (!rootRef.current?.contains(event.target as Node)) setOpen(false); };
    document.addEventListener("pointerdown", close);
    return () => document.removeEventListener("pointerdown", close);
  }, [open]);
  useEffect(() => { if (disabled) setOpen(false); }, [disabled]);

  const closeAndReturn = () => { setOpen(false); triggerRef.current?.focus(); };
  const locked = recording ? t("panel:settingsLocked") : undefined;

  return <span className="panel-settings-root" ref={rootRef}
    onBlur={event => { const next = event.relatedTarget as Node | null; if (open && next && !rootRef.current?.contains(next)) setOpen(false); }}>
    <button ref={triggerRef} type="button" className="panel-control-group panel-settings-button" aria-label={t("panel:settings")} title={t("panel:settings")}
      aria-haspopup="dialog" aria-expanded={open} aria-controls={open ? popoverId : undefined} disabled={disabled}
      onClick={() => { setOpen(value => !value); }}
      onKeyDown={event => { if (event.key === "ArrowDown" && !open) { event.preventDefault(); setOpen(true); } }}>
      <Icon icon={SlidersHorizontal} size={16} />
    </button>
    {open && <div id={popoverId} role="dialog" aria-label={t("panel:settings")} className="panel-settings-popover" tabIndex={-1}
      onKeyDown={event => { if (event.key === "Escape") { event.preventDefault(); event.stopPropagation(); closeAndReturn(); } }}>
      <Row icon={Timer}>
        <label className="panel-settings-label" htmlFor={countdownId}>{t("panel:countdown")}</label>
        <select id={countdownId} value={settings.countdownSeconds} disabled={recording} title={locked}
          onChange={event => onChange({ countdownSeconds: Number(event.target.value) as RecordingSettings["countdownSeconds"] })}>
          {COUNTDOWN_OPTIONS.map(seconds => <option key={seconds} value={seconds}>{seconds === 0 ? t("panel:countdownOff") : t("panel:countdownSeconds", { seconds })}</option>)}
        </select>
      </Row>
      <Row icon={MonitorPlay}>
        <label className="panel-settings-label" htmlFor={resolutionId}>{t("panel:resolution")}</label>
        <select id={resolutionId} value={settings.resolution} disabled={recording} title={locked} aria-describedby={hintId}
          onChange={event => onChange({ resolution: event.target.value as RecordingResolution })}>
          {RESOLUTIONS.map(resolution => <option key={resolution} value={resolution}>{resolution}</option>)}
        </select>
      </Row>
      <p id={hintId} className="panel-settings-hint">{locked ?? t("panel:resolutionHint")}</p>
      <SwitchRow icon={PanelBottom} label={t("panel:controlBar")} title={t("panel:controlBarHint")} checked={settings.showControlBar} onToggle={() => onChange({ showControlBar: !settings.showControlBar })} />
      <SwitchRow icon={MicOff} label={t("panel:micWarning")} checked={!settings.skipMicWarning} onToggle={() => onChange({ skipMicWarning: !settings.skipMicWarning })} />
      {error && <p role="alert" className="panel-settings-hint">{error}</p>}
    </div>}
  </span>;
}
