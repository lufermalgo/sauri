import { useId, type InputHTMLAttributes, type ReactNode } from "react";

export type TextFieldProps = InputHTMLAttributes<HTMLInputElement> & {
  label: ReactNode;
  error?: string;
  /** Control rendered inside the field, at its end (e.g. a show/hide button). The caller gives it an accessible name. */
  trailing?: ReactNode;
};

export function TextField({ label, error, trailing, id, className = "", "aria-describedby": describedBy, ...props }: TextFieldProps) {
  const generatedId = useId();
  const inputId = id ?? generatedId;
  const errorId = `${inputId}-error`;
  const description = [describedBy, error ? errorId : undefined].filter(Boolean).join(" ") || undefined;
  const input = <input {...props} id={inputId} className={`ui-input ${trailing ? "ui-input--has-trailing" : ""} ${className}`}
    aria-invalid={error ? true : props["aria-invalid"]} aria-describedby={description} />;
  return <div className="ui-text-field">
    <label htmlFor={inputId}>{label}</label>
    {trailing ? <div className="ui-input-wrap">{input}<div className="ui-input-trailing">{trailing}</div></div> : input}
    {error && <span id={errorId} className="ui-field-error" role="alert">{error}</span>}
  </div>;
}
