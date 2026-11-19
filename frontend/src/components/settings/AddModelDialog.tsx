import { useState } from "react";
import { ArrowLeft } from "lucide-react";
import type { EngineProcess, LocalHardware, LocalJob, LocalModel, LocalRecommendation } from "@sauri/shared-types";
import { Button, Dialog, Icon, StatusBadge } from "../ui";
import { CustomModelForm } from "./CustomModelForm";
import type { CustomInstallRequest, CustomModelProcess } from "./customModelsApi";
import { availabilityOf, formatBytes, formatMemory } from "./engineLabels";
import { JobProgress, ManagedHow, roomNote } from "./LocalModelRow";
import { addable, chipName, displayName, isManaged, reasonText, shortNote, suggestionsFor } from "./localModelState";
import { useT } from "../../i18n";

/** Processes that accept a model of the person's own: speakers run on Sauri's engine only. */
function acceptsCustom(process: EngineProcess): process is CustomModelProcess {
  return process === "transcription" || process === "summary";
}

export type Outcome = { kind: "success" | "error"; text: string } | null;

export interface AddModelDialogProps {
  process: EngineProcess;
  /** The choices of the process (see `splitEntries`), installed or not. */
  options: LocalModel[];
  hardware: LocalHardware;
  recommendation: LocalRecommendation | undefined;
  job: LocalJob | null;
  cancelling: boolean;
  busy: boolean;
  /** The card's last result, shown here while the dialog covers the card. */
  outcome: Outcome;
  onInstall: (model: LocalModel) => void;
  /** Starts the download of a model of the person's own; resolves with its job, or null when it was refused. */
  onInstallCustom: (request: CustomInstallRequest) => Promise<LocalJob | null>;
  onCancel: () => void;
  onClose: () => void;
}

/** «Agregar»: at most two models that suit this computer, each with its size, why it is suggested and «Instalar»
 * (progress and «Cancelar» while it downloads), and, for transcription and summaries, «Otro modelo…» to bring one
 * from Hugging Face. Nothing here asks for an account or a key. */
export function AddModelDialog(props: AddModelDialogProps) {
  const { t } = useT();
  const { process, outcome, onClose } = props;
  // «returned» is the suggestions again after «Otro»: the focus goes back to the button that left them.
  const [view, setView] = useState<"suggestions" | "custom" | "returned">("suggestions");

  return (
    <Dialog title={t(`engines:local.add.title.${process}`)} closeLabel={t("engines:local.add.close")} onClose={onClose}>
      <div className="local-add">
        {view !== "custom" ? (
          <Suggestions {...props} allowsCustom={acceptsCustom(process)} returned={view === "returned"} onOther={() => setView("custom")} />
        ) : acceptsCustom(process) && (
          <>
            <Button variant="ghost" size="sm" className="local-add-back" onClick={() => setView("returned")}>
              <Icon icon={ArrowLeft} />
              {t("engines:local.custom.back")}
            </Button>
            <CustomModelForm
              process={process}
              job={props.job}
              cancelling={props.cancelling}
              busy={props.busy}
              onInstall={props.onInstallCustom}
              onCancel={props.onCancel}
            />
          </>
        )}
        <div role="status" className="settings-notice">{outcome?.kind === "success" ? outcome.text : null}</div>
        {outcome?.kind === "error" && <p role="alert" className="ui-field-error settings-notice">{outcome.text}</p>}
      </div>
    </Dialog>
  );
}

function Suggestions(props: AddModelDialogProps & { allowsCustom: boolean; returned: boolean; onOther: () => void }) {
  const { t } = useT();
  const { process, options, hardware, recommendation, job, cancelling, busy, onInstall, onCancel, allowsCustom, returned, onOther } = props;
  const suggestions = suggestionsFor(options, hardware, recommendation);
  const jobRunning = job?.state === "running";
  const nothingLeft = addable(options).length === 0;
  const missingEngines = options.filter((model) => isManaged(model) && availabilityOf(model) === "available");

  const computer = t("engines:local.hardwareShort", {
    chip: chipName(hardware.arch, hardware.system),
    memory: formatMemory(hardware.memory_gib),
    free: formatBytes(hardware.disk_free_bytes),
  });

  return (
    <>
      {/* The computer the suggestions were chosen for; when no local model fits, why. */}
      <p className="settings-help">
        {t("engines:local.add.intro", { computer })}
        {recommendation && !recommendation.model_id && ` ${reasonText(recommendation, hardware)}`}
      </p>
      {suggestions.length > 0 ? (
        <section className="local-add-section" aria-labelledby={`local-add-suggested-${process}`}>
          <h3 id={`local-add-suggested-${process}`} className="settings-group-title">{t("engines:local.add.suggested")}</h3>
          <ul className="engines-local-models">
            {suggestions.map((model, index) => {
              const running = jobRunning && job.model_id === model.id ? job : null;
              const name = displayName(model);
              const titleId = `local-add-${process}-${model.id}`;
              const recommendedHere = recommendation?.model_id === model.id;
              const reason = recommendedHere && recommendation ? reasonText(recommendation, hardware) : shortNote(model, options);
              const room = roomNote(model);
              return (
                <li key={model.id} className="engines-local-row" aria-labelledby={titleId}>
                  <div className="engines-local-row-main">
                    <div className="engines-local-row-head">
                      <span id={titleId} className="engines-local-model-name">{name}</span>
                      {(recommendedHere || model.recommended) && <StatusBadge tone="success">{t("engines:local.tags.recommended")}</StatusBadge>}
                    </div>
                    <p className="settings-help local-row-line">
                      {model.size !== null && <span className="engines-local-size">{formatBytes(model.size)}</span>}
                      <span>{reason}</span>
                    </p>
                    {room && <p className="settings-help">{room}</p>}
                  </div>
                  {running ? (
                    <JobProgress job={running} name={name} cancelling={cancelling} onCancel={onCancel} />
                  ) : (
                    <div className="engines-local-row-actions">
                      <Button
                        variant={index === 0 ? "primary" : "secondary"}
                        size="sm"
                        aria-label={t("engines:local.installLabel", { id: name })}
                        disabled={jobRunning || busy || room !== null}
                        onClick={() => onInstall(model)}
                      >
                        {t("engines:local.install")}
                      </Button>
                    </div>
                  )}
                </li>
              );
            })}
          </ul>
          {jobRunning && !suggestions.some((model) => model.id === job.model_id) && <p className="settings-help">{t("engines:local.busy")}</p>}
        </section>
      ) : (
        <div className="local-add-section">
          <p>{t(nothingLeft ? "engines:local.add.allInstalled" : "engines:local.add.noneFits")}</p>
          {missingEngines.map((model) => <ManagedHow key={model.id} model={model} />)}
        </div>
      )}

      {allowsCustom && (
        <section className="local-add-section local-add-other" aria-labelledby={`local-add-other-${process}`}>
          <h3 id={`local-add-other-${process}`} className="settings-group-title">{t("engines:local.add.otherTitle")}</h3>
          <p className="settings-help">{t("engines:local.add.otherHelp")}</p>
          <div>
            <Button variant="secondary" size="sm" autoFocus={returned} onClick={onOther}>{t("engines:local.add.other")}</Button>
          </div>
        </section>
      )}
    </>
  );
}
