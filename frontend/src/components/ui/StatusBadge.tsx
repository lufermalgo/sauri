import type { HTMLAttributes } from "react";

export type StatusBadgeProps = HTMLAttributes<HTMLSpanElement> & {
  tone: "neutral" | "progress" | "success" | "error";
  /** Adds a leading dot in the badge's own color. The state is still written in the text. */
  dot?: boolean;
};

export function StatusBadge({ tone, dot = false, className = "", children, ...props }: StatusBadgeProps) {
  return (
    <span {...props} className={`ui-status-badge ui-status-badge--${tone} ${dot ? "ui-status-badge--dot" : ""} ${className}`}>
      {dot && <span className="ui-status-badge-dot" aria-hidden="true" />}
      {children}
    </span>
  );
}
