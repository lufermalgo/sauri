// Design system references for inline styles. The values live in tokens.css (single source,
// both themes); these constants are CSS variable references so inline styles follow the theme.
// Contract: DESIGN.md at the repo root.

export const COLOR_TOKENS = {
  background: "var(--ds-bg)",
  surface: "var(--ds-surface)",
  surfaceAlt: "var(--ds-fill-hover)",
  primary: "var(--ds-accent)",
  text: "var(--ds-fg)",
  textMuted: "var(--ds-fg-muted)",
  error: "var(--ds-danger-text)",
  recording: "var(--ds-recording)",
  focus: "var(--ds-focus)",
  onSpeaker: "var(--ds-on-speaker)",
} as const;

export const TYPOGRAPHY_TOKENS = {
  baseFont: "var(--ds-font-sans)",
  textSm: "var(--ds-text-sm)",
  textBase: "var(--ds-text-md)",
  textLg: "var(--ds-text-base)",
  textXl: "var(--ds-text-xl)",
  weightRegular: 400,
  weightMedium: 500,
  weightSemibold: 600,
} as const;

export const SPACING_TOKENS = {
  space1: "var(--ds-space-1)",
  space2: "var(--ds-space-2)",
  space3: "var(--ds-space-3)",
  space4: "var(--ds-space-4)",
  space5: "var(--ds-space-6)",
  space6: "var(--ds-space-8)",
} as const;

export const RADIUS_TOKENS = {
  radiusSm: "var(--ds-radius-sm)",
  radiusMd: "var(--ds-radius-md)",
  radiusLg: "var(--ds-radius-lg)",
} as const;

export const ELEVATION_TOKENS = {
  shadowSm: "var(--ds-shadow-sm)",
  shadowMd: "var(--ds-shadow-md)",
} as const;

/**
 * Ordered speaker avatar palette (Req. 8.4), shared with the portal.
 * `avatarColor(sequence)` indexes this palette cyclically.
 */
export const AVATAR_PALETTE: string[] = [
  "var(--ds-speaker-1)",
  "var(--ds-speaker-2)",
  "var(--ds-speaker-3)",
  "var(--ds-speaker-4)",
  "var(--ds-speaker-5)",
  "var(--ds-speaker-6)",
];

/** Visible focus ring (Req. 12.4): 2px, offset 2px, theme-aware color. */
export const FOCUS_RING = {
  color: COLOR_TOKENS.focus,
  width: "var(--ds-focus-width)",
  offset: "var(--ds-focus-offset)",
} as const;
