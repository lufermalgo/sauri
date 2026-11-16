import type { ButtonHTMLAttributes } from "react";

export type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant: "primary" | "secondary" | "ghost" | "danger";
  /** Control height on desktop: sm 28, md 32 (default), lg 36. Touch screens use 44 for all. */
  size?: "sm" | "md" | "lg";
};

export function Button({ variant, size = "md", type = "button", className = "", ...props }: ButtonProps) {
  return <button {...props} type={type} className={`ui-button ui-button--${variant} ui-button--${size} ${className}`} />;
}
