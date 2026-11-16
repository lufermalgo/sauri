import React from "react";
import type { LucideIcon, LucideProps } from "lucide-react";
import { ICON_SIZE, ICON_STROKE_WIDTH } from "./iconDefaults";

export interface IconProps extends Omit<LucideProps, "ref"> {
  icon: LucideIcon;
}

/** Decorative Lucide icon: hidden from assistive tech, colored by the parent's text color.
 * Icon-only buttons must carry their own accessible name. */
export function Icon({ icon: Glyph, size = ICON_SIZE, strokeWidth = ICON_STROKE_WIDTH, ...props }: IconProps) {
  return <Glyph size={size} strokeWidth={strokeWidth} aria-hidden="true" focusable="false" {...props} />;
}
