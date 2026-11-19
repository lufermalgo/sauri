import { useId } from "react";
import { ChevronRight } from "lucide-react";
import type { EngineKindInfo, EngineProviderKind } from "@sauri/shared-types";
import { Dialog, Icon } from "../ui";
import { isLocalApp, processList } from "./engineLabels";
import { ProviderLogo } from "./ProviderLogo";
import { t, useT } from "../../i18n";

/** Where the provider runs, in the words the list uses. */
function whereLine(info: EngineKindInfo): string {
  if (info.auth === "account") return t("engines:addDialog.where.account");
  if (isLocalApp(info.kind)) return t("engines:addDialog.where.local");
  if (info.kind === "openai_compatible") return t("engines:addDialog.where.server");
  return t("engines:addDialog.where.cloud");
}

function servesLine(info: EngineKindInfo): string {
  const processes = info.capabilities.map((entry) => entry.capability);
  return processes.length > 0 ? processList(processes) : t("engines:addDialog.servesNone");
}

interface AddProviderDialogProps {
  /** The kinds the person can add now, in the order the API listed them. */
  kinds: EngineKindInfo[];
  onChoose: (kind: EngineProviderKind) => void;
  onClose: () => void;
}

/** The list behind «Agregar proveedor»: every kind Sauri can link, with its logo, its name and one short line
 * saying where it runs and what it is for. Choosing one opens that kind's set-up dialog. */
export function AddProviderDialog({ kinds, onChoose, onClose }: AddProviderDialogProps) {
  const { t } = useT();
  const ids = useId();
  return (
    <Dialog title={t("engines:addDialog.title")} closeLabel={t("engines:addDialog.close")} onClose={onClose}>
      <p className="settings-help engines-add-intro">{t("engines:addDialog.intro")}</p>
      {kinds.length === 0 ? (
        <p className="settings-help">{t("engines:addDialog.none")}</p>
      ) : (
        <ul className="engines-add-list" aria-label={t("engines:addDialog.listLabel")}>
          {kinds.map((info) => {
            const nameId = `${ids}-${info.kind}-name`;
            const lineId = `${ids}-${info.kind}-line`;
            const label = t(`engines:kinds.${info.kind}.label`);
            return (
              <li key={info.kind}>
                <button
                  type="button"
                  className="engines-add-option"
                  aria-labelledby={nameId}
                  aria-describedby={lineId}
                  onClick={() => onChoose(info.kind)}
                >
                  <ProviderLogo kind={info.kind} name={label} />
                  <span className="engines-add-option-text">
                    <span id={nameId} className="engines-add-option-name">{label}</span>
                    <span id={lineId} className="engines-add-option-line">
                      {t("engines:addDialog.line", { where: whereLine(info), serves: servesLine(info) })}
                    </span>
                  </span>
                  <Icon icon={ChevronRight} size={16} className="engines-add-option-chevron" />
                </button>
              </li>
            );
          })}
        </ul>
      )}
    </Dialog>
  );
}
