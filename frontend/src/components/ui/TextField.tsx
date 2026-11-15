import { useId, type InputHTMLAttributes, type ReactNode } from "react";

export type TextFieldProps = InputHTMLAttributes<HTMLInputElement> & {
  label: ReactNode;
  error?: string;
};

export function TextField({ label, error, id, className = "", "aria-describedby": describedBy, ...props }: TextFieldProps) {
  const generatedId = useId();
  const inputId = id ?? generatedId;
  const errorId = `${inputId}-error`;
  const description = [describedBy, error ? errorId : undefined].filter(Boolean).join(" ") || undefined;
  return <div className="ui-text-field">
    <label htmlFor={inputId}>{label}</label>
    <input {...props} id={inputId} className={`ui-input ${className}`}
      aria-invalid={error ? true : props["aria-invalid"]} aria-describedby={description} />
    {error && <span id={errorId} className="ui-field-error" role="alert">{error}</span>}
  </div>;
}
