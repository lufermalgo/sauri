import React, { useEffect, useRef } from "react";
import { MicOff } from "lucide-react";
import { Icon } from "../../core/design/Icon";
import { useT } from "../../i18n";

export function MicrophoneWarning({ skip, onSkip, onContinue, onDismiss, pending, error }: {
  pending?: boolean;
  error?: string | null;
  skip: boolean;
  onSkip: (skip: boolean) => void;
  onContinue: (enableMicrophone: boolean) => void;
  onDismiss: () => void;
}) {
  const { t } = useT();
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const dialog = ref.current!;
    dialog.showModal();
    return () => dialog.close();
  }, []);
  return <dialog className="panel-mic-dialog" ref={ref} aria-labelledby="mic-off-heading" aria-describedby="mic-off-description" onCancel={event => { if (pending) event.preventDefault(); else onDismiss(); }}>
    <div className="panel-stack">
      <span className="panel-warning-icon" aria-hidden="true"><Icon icon={MicOff} size={24} /></span>
      <h2 id="mic-off-heading">{t("panel:micOffHeading")}</h2>
      <p id="mic-off-description">{t("panel:micOffDescription")}</p>
      <button disabled={pending} className="panel-primary" onClick={() => onContinue(true)}>{t("panel:enableMic")}</button>
      <button disabled={pending} onClick={() => onContinue(false)}>{t("panel:withoutMic")}</button>
      {error && <p role="alert">{error}</p>}
      <label className="panel-row"><input disabled={pending} type="checkbox" checked={skip} onChange={event => onSkip(event.target.checked)} />{t("panel:skipWarning")}</label>
    </div>
  </dialog>;
}
