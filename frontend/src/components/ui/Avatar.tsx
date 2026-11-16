import type { CSSProperties, ReactNode } from "react";

export type AvatarProps = {
  initials: ReactNode;
  color: string;
  size?: "sm" | "md";
};

export function Avatar({ initials, color, size = "md" }: AvatarProps) {
  const style = { "--avatar-color": color } as CSSProperties;
  return <span aria-hidden="true" className={`ui-avatar ui-avatar--${size}`} style={style}>{initials}</span>;
}
