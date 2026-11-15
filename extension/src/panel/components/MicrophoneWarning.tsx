import React, { useEffect, useRef } from "react";
import { panelCopy as copy } from "../copy";

export function MicrophoneWarning({ skip, onSkip, onContinue, onDismiss, pending, error }: {
  pending?: boolean;
  error?: string | null;
  skip: boolean;
  onSkip: (skip: boolean) => void;
  onContinue: (enableMicrophone: boolean) => void;
  onDismiss: () => void;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const dialog = ref.current!;
    dialog.showModal();
    return () => dialog.close();
  }, []);
  return <dialog className="panel-mic-dialog" ref={ref} aria-labelledby="mic-off-heading" aria-describedby="mic-off-description" onCancel={event => { if (pending) event.preventDefault(); else onDismiss(); }}>
    <div className="panel-stack">
      <span className="panel-warning-icon" aria-hidden="true">⚠</span>
      <h2 id="mic-off-heading">{copy.micOffHeading}</h2>
      <p id="mic-off-description">{copy.micOffDescription}</p>
      <button disabled={pending} className="panel-primary" onClick={() => onContinue(true)}>{copy.enableMic}</button>
      <button disabled={pending} onClick={() => onContinue(false)}>{copy.withoutMic}</button>
      {error && <p role="alert">{error}</p>}
      <label className="panel-row"><input disabled={pending} type="checkbox" checked={skip} onChange={event => onSkip(event.target.checked)} />{copy.skipWarning}</label>
    </div>
  </dialog>;
}
