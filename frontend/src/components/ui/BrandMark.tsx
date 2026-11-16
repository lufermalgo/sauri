import { useId } from "react";

export interface BrandMarkProps {
  /** Rendered width and height in px. Sizes up to SMALL_VARIANT_MAX use the small variant. */
  size?: number;
  /** Accessible name. Omit it when a visible "Sauri" sits next to the mark: the mark is then decorative. */
  title?: string;
  className?: string;
}

/** Largest size (px) that uses the small variant (wider gap, bigger diamond), see brand/README.md. */
export const SMALL_VARIANT_MAX = 32;

export const DARK_HALF = "#4a7c59";
export const LIGHT_HALF = "#78a886";

// Geometry copied from brand/sauri-isotype.svg (master) and brand/sauri-isotype-small.svg (small).
export const BRAND_SHAPES = {
  master: {
    rect: { x: 0, y: 0, width: 100, height: 100, rx: 30 },
    dark: "-10,-10 108.3,-10 54.4,43.9 50,39.5 39.5,50 43.9,54.4 -10,108.3",
    light: "110,110 110,-8.3 56.1,45.6 60.5,50 50,60.5 45.6,56.1 -8.3,110",
  },
  small: {
    rect: { x: 0, y: 0, width: 100, height: 100, rx: 27 },
    dark: "-10,-10 105.76,-10 54.88,40.88 50,36 36,50 40.88,54.88 -10,105.76",
    light: "110,110 110,-5.76 59.12,45.12 64,50 50,64 45.12,59.12 -5.76,110",
  },
} as const;

/** Sauri isotype drawn inline: two green halves split by a diagonal gap, with a diamond in the center. */
export function BrandMark({ size = 24, title, className }: BrandMarkProps) {
  const clipId = `brand-mark-${useId().replace(/[^a-zA-Z0-9_-]/g, "")}`;
  const shape = BRAND_SHAPES[size <= SMALL_VARIANT_MAX ? "small" : "master"];
  const a11y = title ? { role: "img", "aria-label": title } : { "aria-hidden": true as const };
  return (
    <svg className={className} width={size} height={size} viewBox="0 0 100 100" focusable="false" {...a11y}>
      <defs>
        <clipPath id={clipId}>
          <rect {...shape.rect} />
        </clipPath>
      </defs>
      <g clipPath={`url(#${clipId})`}>
        <polygon fill={DARK_HALF} points={shape.dark} />
        <polygon fill={LIGHT_HALF} points={shape.light} />
      </g>
    </svg>
  );
}
