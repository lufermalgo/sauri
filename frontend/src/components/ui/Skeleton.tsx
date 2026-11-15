import type { CSSProperties } from "react";

export type SkeletonProps = {
  width?: string | number;
  height?: string | number;
  radius?: "sm" | "md" | "full";
  className?: string;
};

export function Skeleton({ width, height, radius = "sm", className = "" }: SkeletonProps) {
  const style: CSSProperties = { width, height };
  return <span aria-hidden="true" className={`ui-skeleton ui-skeleton--${radius} ${className}`.trim()} style={style} />;
}

export type SkeletonLinesProps = {
  lines: number;
  lastWidth?: string;
};

const LINE_WIDTHS = ["100%", "92%", "96%", "88%"];

export function SkeletonLines({ lines, lastWidth = "60%" }: SkeletonLinesProps) {
  const count = Math.max(0, Math.floor(lines));
  return (
    <span aria-hidden="true" className="ui-skeleton-lines">
      {Array.from({ length: count }, (_, index) => (
        <Skeleton key={index} height={14}
          width={index === count - 1 && count > 1 ? lastWidth : LINE_WIDTHS[index % LINE_WIDTHS.length]} />
      ))}
    </span>
  );
}
