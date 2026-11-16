import React from "react";
import type { CaptureState } from "../../core/types";
import { panelCopy as copy } from "../copy";
import { BrandLogo } from "../../core/design/BrandLogo";

export interface PanelHeaderProps {
  captureState?: CaptureState;
  paused?: boolean;
}

export function PanelHeader({ captureState = "idle", paused }: PanelHeaderProps) {
  return <header className="panel-header">
    <span className="panel-brand">
      <BrandLogo height={24} title={copy.brandName} />
      <span className="panel-title panel-ellipsis">{copy.panelTitle}</span>
    </span>
    {captureState === "recording" && <span className="panel-badge panel-badge-recording"><span className={paused ? "panel-dot" : "panel-dot panel-record-dot"} aria-hidden="true" />{paused ? copy.paused : copy.recording}</span>}
  </header>;
}
