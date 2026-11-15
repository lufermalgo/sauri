import type { ProgressHTMLAttributes } from "react";

export type ProgressBarProps = Omit<ProgressHTMLAttributes<HTMLProgressElement>, "children" | "value"> & {
  label: string;
  /** Omit for an indeterminate bar; a number makes it determinate. */
  value?: number;
  /** Spoken alternative to the raw number, e.g. "≈ 42 %, estimated". */
  valueText?: string;
};

export function ProgressBar({ label, value, max = 100, valueText, className = "", ...props }: ProgressBarProps) {
  const determinate = typeof value === "number";
  return <progress {...props} className={`ui-progress ${determinate ? "ui-progress--determinate" : ""} ${className}`}
    max={max} value={value} aria-label={label}
    aria-valuemin={determinate ? 0 : undefined}
    aria-valuemax={determinate ? Number(max) : undefined}
    aria-valuenow={determinate ? value : undefined}
    aria-valuetext={determinate ? valueText : undefined} />;
}
