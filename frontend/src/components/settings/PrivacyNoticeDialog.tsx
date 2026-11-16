import { TriangleAlert } from "lucide-react";
import type { EnginePrivacyNotice } from "@sauri/shared-types";
import { copy } from "../../copy/es";
import { Button, Dialog, Icon } from "../ui";

const text = copy.engines.notice;

interface PrivacyNoticeDialogProps {
  notice: EnginePrivacyNotice;
  /** Cautions about this particular choice (a double send, an unvalidated result), shown before the buttons. */
  warnings?: string[];
  /** True while the choice is being saved; the dialog cannot be dismissed meanwhile. */
  busy: boolean;
  error: string | null;
  onAccept: () => void;
  onCancel: () => void;
}

/** What leaves this computer and where it goes, shown before a process is switched to an external
 * provider. The words and their version come from the API; nothing is saved until "Aceptar y usar". */
export function PrivacyNoticeDialog({ notice, warnings = [], busy, error, onAccept, onCancel }: PrivacyNoticeDialogProps) {
  return (
    <Dialog title={notice.title} closeLabel={text.close} onClose={busy ? () => undefined : onCancel}>
      <div className="settings-form engines-notice">
        {notice.paragraphs.map((paragraph, index) => (
          <p key={index} className="engines-notice-paragraph">{paragraph}</p>
        ))}
        <p className="settings-help engines-notice-address">{text.address(notice.address)}</p>
        {warnings.map((warning) => (
          <p key={warning} role="note" className="engines-warning">
            <Icon icon={TriangleAlert} />
            <span>{warning}</span>
          </p>
        ))}
        {error && <p role="alert" className="ui-field-error">{error}</p>}
        <div className="ui-dialog-actions">
          <Button variant="secondary" disabled={busy} onClick={onCancel}>{text.cancel}</Button>
          <Button variant="primary" disabled={busy} onClick={onAccept}>{busy ? text.accepting : text.accept}</Button>
        </div>
      </div>
    </Dialog>
  );
}
