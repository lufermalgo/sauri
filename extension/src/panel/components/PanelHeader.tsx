import React from "react";
import type { CaptureState } from "../../core/types";
import { panelCopy as copy } from "../copy";

export interface PanelHeaderProps {
  captureState?: CaptureState;
  paused?: boolean;
  onOpenSettings?: () => void;
}

export function PanelHeader({ captureState = "idle", paused, onOpenSettings }: PanelHeaderProps) {
  return <header className="panel-header">
    <span className="panel-brand">
      <svg width="24" height="24" viewBox="0 0 26 26" fill="none" aria-hidden="true">
        <circle cx="13" cy="13" r="13" fill="currentColor" />
        <path d="M8 13v0M11 9.5v7M14 7v12M17 10.5v5" stroke="white" strokeWidth="1.8" strokeLinecap="round" />
      </svg>{copy.brand}
    </span>
    {captureState === "recording" ? <span className="panel-badge panel-badge-recording"><span className={paused ? "" : "panel-record-dot"} aria-hidden="true">●</span>{paused ? copy.paused : copy.recording}</span>
      : onOpenSettings && <button className="panel-icon-button" aria-label={copy.settings} onClick={onOpenSettings}>
        <svg width="20" height="20" viewBox="0 0 20 20" fill="none" aria-hidden="true"><circle cx="10" cy="10" r="2.6" stroke="currentColor" strokeWidth="1.6" /><path d="M10 2.5v2M10 15.5v2M2.5 10h2M15.5 10h2M4.7 4.7l1.4 1.4M13.9 13.9l1.4 1.4M4.7 15.3l1.4-1.4M13.9 6.1l1.4-1.4" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" /></svg>
      </button>}
  </header>;
}
