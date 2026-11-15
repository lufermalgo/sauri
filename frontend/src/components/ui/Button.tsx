import type { ButtonHTMLAttributes } from "react";

export type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant: "primary" | "secondary" | "ghost" | "danger";
};

export function Button({ variant, type = "button", className = "", ...props }: ButtonProps) {
  return <button {...props} type={type} className={`ui-button ui-button--${variant} ${className}`} />;
}
