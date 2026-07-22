// Speaking_Time_View — Req. 10.1-10.7
import React from "react";
import type { ViewState, SpeakingTimeEntry } from "../core/types";
import { formatTimestamp } from "../core/time";
import { labelInitials, avatarColor } from "../core/speakers";
import { sortSpeakingTime } from "../core/order";
import { COLOR_TOKENS, SPACING_TOKENS, RADIUS_TOKENS, TYPOGRAPHY_TOKENS } from "../core/design/tokens";

export interface SpeakingTimeViewProps {
  state: ViewState;
  entries: SpeakingTimeEntry[];
  onRetry: () => void;
}

export function SpeakingTimeView({ state, entries, onRetry }: SpeakingTimeViewProps) {
  const sorted = sortSpeakingTime(entries);

  return (
    <section aria-label="Speaking time" style={{ display: "flex", flexDirection: "column", gap: SPACING_TOKENS.space2 }}>
      <h2 style={{ fontSize: TYPOGRAPHY_TOKENS.textLg, margin: 0 }}>Speaking time</h2>

      {state === "loading" && <p>Loading speaking time...</p>}

      {state === "error" && (
        <div>
          <p style={{ color: COLOR_TOKENS.error }}>Couldn't load speaking time.</p>
          <button type="button" onClick={onRetry}>
            Retry
          </button>
        </div>
      )}

      {state === "empty" && <p>Speaking time is not available for this note.</p>}

      {state === "withData" && (
        <ul style={{ listStyle: "none", margin: 0, padding: 0, display: "flex", flexDirection: "column", gap: SPACING_TOKENS.space2 }}>
          {sorted.map((entry) => (
            <li
              key={entry.speaker.id}
              style={{
                display: "flex",
                alignItems: "center",
                gap: SPACING_TOKENS.space3,
                padding: SPACING_TOKENS.space2,
                borderRadius: RADIUS_TOKENS.radiusMd,
                backgroundColor: COLOR_TOKENS.surface,
              }}
            >
              <div
                aria-hidden
                style={{
                  flexShrink: 0,
                  width: "28px",
                  height: "28px",
                  borderRadius: "50%",
                  backgroundColor: avatarColor(entry.speaker.sequence),
                  color: COLOR_TOKENS.text,
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  fontSize: TYPOGRAPHY_TOKENS.textSm,
                  fontWeight: TYPOGRAPHY_TOKENS.weightSemibold,
                }}
              >
                {labelInitials(entry.speaker.label)}
              </div>
              <span style={{ fontWeight: TYPOGRAPHY_TOKENS.weightMedium }}>{entry.speaker.label}</span>
              <span style={{ marginLeft: "auto", color: COLOR_TOKENS.textMuted, fontSize: TYPOGRAPHY_TOKENS.textSm }}>
                {formatTimestamp(entry.timeMs)}
              </span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
