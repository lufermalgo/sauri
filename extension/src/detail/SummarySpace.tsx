// Summary_Space — reserved structural region, no AI generation (Req. 7.2, 7.3)
import React from "react";
import { COLOR_TOKENS, SPACING_TOKENS, RADIUS_TOKENS, TYPOGRAPHY_TOKENS } from "../core/design/tokens";

export function SummarySpace() {
  return (
    <section
      aria-label="Summary"
      style={{
        padding: SPACING_TOKENS.space4,
        borderRadius: RADIUS_TOKENS.radiusMd,
        backgroundColor: COLOR_TOKENS.surface,
        color: COLOR_TOKENS.textMuted,
      }}
    >
      <h2 style={{ fontSize: TYPOGRAPHY_TOKENS.textLg, margin: 0, color: COLOR_TOKENS.text }}>Summary</h2>
      <p style={{ margin: `${SPACING_TOKENS.space2} 0 0` }}>Summary available soon.</p>
    </section>
  );
}
