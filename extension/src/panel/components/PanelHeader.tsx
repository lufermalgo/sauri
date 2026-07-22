// Panel_Header — Req. 2.1, 2.2, 2.3, 2.4, 2.5, 2.6
import React from "react";
import { newNoteButtonEnabled } from "../../core/capture";
import type { CaptureState } from "../../core/types";
import { COLOR_TOKENS, SPACING_TOKENS, TYPOGRAPHY_TOKENS, RADIUS_TOKENS } from "../../core/design/tokens";

export interface PanelHeaderProps {
  captureState: CaptureState;
  onNewNote: () => void;
  startError?: string | null;
}

export function PanelHeader({ captureState, onNewNote, startError }: PanelHeaderProps) {
  const enabled = newNoteButtonEnabled(captureState);

  return (
    <header
      style={{
        display: "flex",
        flexDirection: "column",
        gap: SPACING_TOKENS.space2,
        padding: SPACING_TOKENS.space4,
      }}
    >
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
        <h1
          style={{
            fontSize: TYPOGRAPHY_TOKENS.textXl,
            fontWeight: TYPOGRAPHY_TOKENS.weightSemibold,
            margin: 0,
          }}
        >
          REC Notes
        </h1>
        <button
          type="button"
          onClick={onNewNote}
          disabled={!enabled}
          style={{
            backgroundColor: enabled ? COLOR_TOKENS.primary : COLOR_TOKENS.textMuted,
            color: COLOR_TOKENS.text,
            border: "none",
            borderRadius: RADIUS_TOKENS.radiusMd,
            padding: `${SPACING_TOKENS.space2} ${SPACING_TOKENS.space3}`,
            fontSize: TYPOGRAPHY_TOKENS.textSm,
            fontWeight: TYPOGRAPHY_TOKENS.weightMedium,
            cursor: enabled ? "pointer" : "not-allowed",
          }}
        >
          + New Note REC
        </button>
      </div>
      {startError && (
        <p role="alert" style={{ color: COLOR_TOKENS.error, fontSize: TYPOGRAPHY_TOKENS.textSm, margin: 0 }}>
          {startError}
        </p>
      )}
    </header>
  );
}
