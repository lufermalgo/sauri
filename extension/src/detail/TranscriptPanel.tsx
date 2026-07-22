// Transcript_Panel and Intervention — Req. 6.4, 6.6, 8.1-8.10, 14.3
import React, { useEffect, useRef } from "react";
import type { ViewState, InterventionDTO } from "../core/types";
import { formatTimestamp } from "../core/time";
import { labelInitials, avatarColor } from "../core/speakers";
import { UNIDENTIFIED_SPEAKER_LABEL } from "../core/interventions";
import { COLOR_TOKENS, SPACING_TOKENS, RADIUS_TOKENS, TYPOGRAPHY_TOKENS } from "../core/design/tokens";

export interface TranscriptPanelProps {
  state: ViewState;
  interventions: InterventionDTO[];
  matchingTurnIds?: string[];
  firstMatchId?: string | null;
  onRetry: () => void;
}

export function TranscriptPanel({
  state,
  interventions,
  matchingTurnIds = [],
  firstMatchId = null,
  onRetry,
}: TranscriptPanelProps) {
  const refsByTurn = useRef<Map<string, HTMLLIElement>>(new Map());

  useEffect(() => {
    if (!firstMatchId) return;
    refsByTurn.current.get(firstMatchId)?.scrollIntoView({ block: "nearest" });
  }, [firstMatchId]);

  return (
    <section aria-label="Transcript" style={{ display: "flex", flexDirection: "column", gap: SPACING_TOKENS.space2 }}>
      <h2 style={{ fontSize: TYPOGRAPHY_TOKENS.textLg, margin: 0 }}>Transcript</h2>

      {state === "loading" && <p>Loading transcript...</p>}

      {state === "error" && (
        <div>
          <p style={{ color: COLOR_TOKENS.error }}>Couldn't load the transcript.</p>
          <button type="button" onClick={onRetry}>
            Retry
          </button>
        </div>
      )}

      {state === "empty" && <p>The transcript is not available for this note.</p>}

      {state === "withData" && (
        <ul
          style={{
            listStyle: "none",
            margin: 0,
            padding: 0,
            display: "flex",
            flexDirection: "column",
            gap: SPACING_TOKENS.space3,
            maxHeight: "480px",
            overflowY: "auto",
          }}
        >
          {interventions.map((intervention) => {
            const label = intervention.speaker?.label ?? UNIDENTIFIED_SPEAKER_LABEL;
            const color = intervention.speaker ? avatarColor(intervention.speaker.sequence) : COLOR_TOKENS.textMuted;
            const highlighted = matchingTurnIds.includes(intervention.turnId);

            return (
              <li
                key={intervention.turnId}
                ref={(el) => {
                  if (el) refsByTurn.current.set(intervention.turnId, el);
                  else refsByTurn.current.delete(intervention.turnId);
                }}
                data-highlighted={highlighted}
                style={{
                  display: "flex",
                  gap: SPACING_TOKENS.space3,
                  padding: SPACING_TOKENS.space2,
                  borderRadius: RADIUS_TOKENS.radiusMd,
                  backgroundColor: highlighted ? COLOR_TOKENS.surfaceAlt : "transparent",
                }}
              >
                <div
                  aria-hidden
                  style={{
                    flexShrink: 0,
                    width: "32px",
                    height: "32px",
                    borderRadius: "50%",
                    backgroundColor: color,
                    color: COLOR_TOKENS.text,
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                    fontSize: TYPOGRAPHY_TOKENS.textSm,
                    fontWeight: TYPOGRAPHY_TOKENS.weightSemibold,
                  }}
                >
                  {labelInitials(label)}
                </div>
                <div style={{ display: "flex", flexDirection: "column", gap: "2px" }}>
                  <div style={{ display: "flex", gap: SPACING_TOKENS.space2, alignItems: "baseline" }}>
                    <span style={{ fontWeight: TYPOGRAPHY_TOKENS.weightMedium }}>{label}</span>
                    <span style={{ fontSize: TYPOGRAPHY_TOKENS.textSm, color: COLOR_TOKENS.textMuted }}>
                      {formatTimestamp(intervention.startMs)}
                    </span>
                  </div>
                  <p style={{ margin: 0 }}>{intervention.text}</p>
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}
