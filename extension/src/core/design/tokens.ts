// Design system: color, typography, spacing, radius, elevation tokens
// and avatar palette, shared by the Side Panel and the Detail View.
// Requirements: 12.1, 12.2, 12.4

export const COLOR_TOKENS = {
  background: "#faf6f0",
  surface: "#ffffff",
  surfaceAlt: "#f0e8db",
  primary: "#4a7c59",
  text: "#2e3230",
  textMuted: "#4a4e4a",
  error: "#b83230",
  recording: "#b83230",
  focus: "#3b6a49",
} as const;

/** Individually exported aliases for contrast tests (Req. 12.4) */
export const FOCUS_RING_COLOR = COLOR_TOKENS.focus;
export const SURFACE_COLOR = COLOR_TOKENS.surface;

export const TYPOGRAPHY_TOKENS = {
  baseFont:
    '"Nunito Sans", system-ui, sans-serif',
  textSm: "12px",
  textBase: "14px",
  textLg: "16px",
  textXl: "20px",
  weightRegular: 400,
  weightMedium: 500,
  weightSemibold: 600,
} as const;

export const SPACING_TOKENS = {
  space1: "4px",
  space2: "8px",
  space3: "12px",
  space4: "16px",
  space5: "24px",
  space6: "32px",
} as const;

export const RADIUS_TOKENS = {
  radiusSm: "4px",
  radiusMd: "8px",
  radiusLg: "16px",
} as const;

export const ELEVATION_TOKENS = {
  shadowSm: "0 1px 2px rgba(0,0,0,0.24)",
  shadowMd: "0 4px 12px rgba(0,0,0,0.32)",
} as const;

/**
 * Ordered color palette for the speaker avatar (Req. 8.4).
 * `avatarColor(sequence)` indexes this palette cyclically.
 */
export const AVATAR_PALETTE: string[] = [
  "#5b8cff",
  "#ff8a5b",
  "#5bffb0",
  "#c65bff",
  "#ffd15b",
  "#5bd4ff",
  "#ff5b8a",
  "#8aff5b",
];

/** Visible focus ring derived from the tokens (Req. 12.4) */
export const FOCUS_RING = {
  color: COLOR_TOKENS.focus,
  width: "2px",
  offset: "2px",
} as const;
