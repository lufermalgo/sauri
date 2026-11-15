import type { ProgressHTMLAttributes } from "react";

export type ProgressBarProps = Omit<ProgressHTMLAttributes<HTMLProgressElement>, "children"> & {
  label: string;
};

export function ProgressBar({ label, value, max = 100, className = "", ...props }: ProgressBarProps) {
  return <progress {...props} className={`ui-progress ${className}`} max={max} value={value} aria-label={label} />;
}
