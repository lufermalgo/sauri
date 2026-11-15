import { useEffect, useId, useRef, type ReactNode } from "react";
import { Button } from "./Button";

export type ConfirmDialogProps = {
  title: string;
  body: ReactNode;
  confirmLabel: string;
  cancelLabel: string;
  onConfirm: () => void;
  onCancel: () => void;
};

export function ConfirmDialog({ title, body, confirmLabel, cancelLabel, onConfirm, onCancel }: ConfirmDialogProps) {
  const id = useId();
  const dialog = useRef<HTMLDialogElement>(null);
  const cancel = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    const modal = dialog.current!;
    modal.showModal();
    cancel.current?.focus();
    return () => { if (modal.open) modal.close(); };
  }, []);

  return <dialog ref={dialog} className="ui-dialog" aria-labelledby={`${id}-title`}
    aria-describedby={`${id}-body`} onCancel={event => { event.preventDefault(); onCancel(); }}>
    <h2 id={`${id}-title`}>{title}</h2>
    <div id={`${id}-body`}>{body}</div>
    <div className="ui-dialog-actions">
      <button ref={cancel} type="button" className="ui-button ui-button--secondary" onClick={onCancel}>{cancelLabel}</button>
      <Button variant="danger" onClick={onConfirm}>{confirmLabel}</Button>
    </div>
  </dialog>;
}
