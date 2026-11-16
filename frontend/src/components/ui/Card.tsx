import type { HTMLAttributes } from "react";

export type CardProps = HTMLAttributes<HTMLElement> & {
  /** Muted card for something that is off: calmer text and mark, never lower contrast than `fg-subtle`. */
  dimmed?: boolean;
  /** Dashed border for something that does not exist yet (a provider not set up, the "add" tile). */
  dashed?: boolean;
};

export function Card({ dimmed = false, dashed = false, className = "", ...props }: CardProps) {
  const state = `${dimmed ? "ui-card--dimmed" : ""} ${dashed ? "ui-card--dashed" : ""}`;
  return <section {...props} className={`ui-card ${state} ${className}`} />;
}
