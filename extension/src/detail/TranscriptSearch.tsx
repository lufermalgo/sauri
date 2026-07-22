// Transcript_Search — Req. 9.1, 9.2, 9.3, 9.4, 9.5
import React, { useEffect, useMemo, useState } from "react";
import type { InterventionDTO } from "../core/types";
import { transcriptMatches, TRANSCRIPT_SEARCH_LIMIT, type TranscriptSearchResult } from "../core/search";
import { SPACING_TOKENS, COLOR_TOKENS, RADIUS_TOKENS } from "../core/design/tokens";

export interface TranscriptSearchProps {
  interventions: InterventionDTO[];
  onResult: (result: TranscriptSearchResult) => void;
}

export function TranscriptSearch({ interventions, onResult }: TranscriptSearchProps) {
  const [text, setText] = useState("");

  const result = useMemo(
    () => transcriptMatches(interventions, text),
    [interventions, text]
  );

  useEffect(() => {
    onResult(result);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [result]);

  const noMatches = text.trim().length > 0 && result.matchingTurnIds.length === 0;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: SPACING_TOKENS.space1 }}>
      <input
        type="text"
        aria-label="Search the transcript"
        placeholder="Search the transcript..."
        maxLength={TRANSCRIPT_SEARCH_LIMIT}
        value={text}
        onChange={(e) => setText(e.target.value)}
        style={{
          padding: SPACING_TOKENS.space2,
          borderRadius: RADIUS_TOKENS.radiusSm,
          border: `1px solid ${COLOR_TOKENS.textMuted}`,
        }}
      />
      {noMatches && (
        <p role="status" style={{ margin: 0, fontSize: "12px", color: COLOR_TOKENS.textMuted }}>
          No matches.
        </p>
      )}
    </div>
  );
}
