import type { HTMLAttributes } from "react";

export type StatusBadgeProps = HTMLAttributes<HTMLSpanElement> & {
  tone: "neutral" | "progress" | "success" | "error";
};

export function StatusBadge({ tone, className = "", ...props }: StatusBadgeProps) {
  return <span {...props} className={`ui-status-badge ui-status-badge--${tone} ${className}`} />;
}
