import React from "react";
import { Settings } from "lucide-react";
import { Icon } from "../../core/design/Icon";
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
    {captureState === "recording" ? <span className="panel-badge panel-badge-recording"><span className={paused ? "panel-dot" : "panel-dot panel-record-dot"} aria-hidden="true" />{paused ? copy.paused : copy.recording}</span>
      : onOpenSettings && <button className="panel-icon-button" aria-label={copy.settings} onClick={onOpenSettings}>
        <Icon icon={Settings} size={20} />
      </button>}
  </header>;
}
