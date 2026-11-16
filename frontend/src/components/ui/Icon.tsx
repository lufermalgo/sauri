import type { LucideIcon, LucideProps } from "lucide-react";

export interface IconProps extends Omit<LucideProps, "ref"> {
  icon: LucideIcon;
}

// Same defaults as extension/src/core/design/iconDefaults.ts (DESIGN.md section 8).
const ICON_SIZE = 18;
const ICON_STROKE_WIDTH = 1.75;

/** Decorative Lucide icon: hidden from assistive tech, colored by the surrounding text. */
export function Icon({ icon: Glyph, size = ICON_SIZE, strokeWidth = ICON_STROKE_WIDTH, ...props }: IconProps) {
  return <Glyph size={size} strokeWidth={strokeWidth} aria-hidden="true" focusable="false" {...props} />;
}
