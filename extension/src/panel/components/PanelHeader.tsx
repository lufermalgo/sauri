import React from "react";
import type { CaptureState } from "../../core/types";
import { useT } from "../../i18n";
import { BrandLogo } from "../../core/design/BrandLogo";

export interface PanelHeaderProps {
  captureState?: CaptureState;
  paused?: boolean;
}

export function PanelHeader({ captureState = "idle", paused }: PanelHeaderProps) {
  const { t } = useT();
  return <header className="panel-header">
    <span className="panel-brand">
      <BrandLogo height={24} title={t("panel:brandName")} />
      <span className="panel-title panel-ellipsis">{t("panel:panelTitle")}</span>
    </span>
    {captureState === "recording" && <span className="panel-badge panel-badge-recording"><span className={paused ? "panel-dot" : "panel-dot panel-record-dot"} aria-hidden="true" />{paused ? t("panel:paused") : t("panel:recording")}</span>}
  </header>;
}
