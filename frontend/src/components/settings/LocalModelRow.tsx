import { useState } from "react";
import type { ReactNode } from "react";
import type { EngineProcess, LocalHardware, LocalJob, LocalModel, LocalRecommendation } from "@sauri/shared-types";
import { isLocalMode } from "../../api";
import { Button, Dialog, Menu, MenuItem, MenuSeparator, ProgressBar, StatusBadge } from "../ui";
import { availabilityOf, formatBytes, formatMemory, processList } from "./engineLabels";
import {
  chipName,
  diskSize,
  displayName,
  isCustom,
  isManaged,
  modelNoteKey,
  originOf,
  percentOf,
  reasonText,
  removalBlock,
  shortNote,
  shortRevision,
  spaceNeeded,
  stateOf,
  tagOf,
  unverifiedText,
} from "./localModelState";
import type { RowState } from "./localModelState";
import { t, translateIfKnown, useT } from "../../i18n";

/** What every row of a process shares: the computer, the running job and the actions the card performs. */
export interface RowContext {
  process: EngineProcess;
  /** Every entry of the process, so a row can name the engine it needs or compare itself with the default. */
  models: LocalModel[];
  hardware: LocalHardware;
  recommendation: LocalRecommendation | undefined;
  job: LocalJob | null;
  cancelling: boolean;
  /** True while an install, check or removal is being started: no other one may start. */
  busy: boolean;
  choosing: boolean;
  externalActive: boolean;
  /** The saved choice (`local:default` or `local:<id>`): what is active follows it, not the host's guess. */
  savedKey: string;
  onUse: (model: LocalModel) => void;
  onInstall: (model: LocalModel) => void;
  onVerify: (model: LocalModel) => void;
  onRemove: (model: LocalModel) => void;
  onCancel: () => void;
}

type RowProps = RowContext & { model: LocalModel };

/** What a row knows about its model; the row shows the short part and «Detalles» the rest. */
interface RowFacts {
  name: string;
  state: RowState;
  installed: boolean;
  managed: boolean;
  component: boolean;
  missingEngine: boolean;
  /** The command that installs the engine a model needs, outside the desktop app. */
  engineCommand: string;
}

/** The line under the name: what needs the person's attention first, else where a model of their own came from,
 * else what the model is good for. */
function rowLine(model: LocalModel, siblings: readonly LocalModel[], facts: RowFacts): string {
  if (facts.state === "unverified" || facts.state === "corrupt") return unverifiedText(model);
  if (facts.missingEngine) return isLocalMode() ? t("engines:local.needsEngineDesktop") : t("engines:local.short.needsEngine");
  const origin = originOf(model);
  if (isCustom(model) && origin) return t("engines:local.custom.origin", { repo: origin.repo, revision: shortRevision(origin.revision) });
  return shortNote(model, siblings);
}

/** An installed model of the process: name, size on disk, its state in words and «Usar este»; checking, removing and
 * «Detalles» live in its «…» menu. While a job runs on it, the row shows the progress and «Cancelar». */
export function ModelRow(props: RowProps) {
  const { t } = useT();
  const { process, model, job, cancelling, busy, choosing, externalActive, savedKey, onUse, onInstall, onVerify, onRemove, onCancel } = props;
  const [detailsOpen, setDetailsOpen] = useState(false);
  const jobRunning = job?.state === "running";
  const running = jobRunning && job.model_id === model.id ? job : null;
  const state = stateOf(model, running, externalActive, savedKey);
  const blocked = jobRunning || busy;
  const managed = isManaged(model);
  const component = model.kind === "component";
  const name = displayName(model);
  const titleId = `engines-model-${process}-${model.id}`;
  const installed = availabilityOf(model) === "installed";
  const missingEngine = installed && model.needs_ready === false;
  const engineEntry = model.needs ? props.models.find((other) => other.id === model.needs) : undefined;
  const facts: RowFacts = {
    name, state, installed, managed, component, missingEngine,
    engineCommand: engineEntry?.managed_by ?? engineEntry?.install?.managed_by ?? "scripts/engines/install-parakeet-engine.sh",
  };
  const canUse = state === "installed" && !missingEngine;
  // An older speaker runtime is replaced by installing the new version over it.
  const canReinstall = component && (state === "unverified" || state === "corrupt") && model.install?.source_available !== false;
  const present = !managed && availabilityOf(model) !== "available" && state !== "verifying";
  const removal = removalBlock(model);
  const tag = tagOf(state);
  const size = diskSize(model);

  return (
    <li className={`engines-local-row${state === "active" ? " engines-local-row--active" : ""}`} aria-labelledby={titleId}>
      <div className="engines-local-row-main">
        <div className="engines-local-row-head">
          <span id={titleId} className="engines-local-model-name">{name}</span>
          {tag && <StatusBadge tone={tag.tone} dot={state === "active"}>{tag.text}</StatusBadge>}
          {isCustom(model) && <StatusBadge tone="neutral">{t("engines:local.tags.custom")}</StatusBadge>}
        </div>
        <p className="settings-help local-row-line">
          {size !== null && <span className="engines-local-size">{formatBytes(size)}</span>}
          <span>{rowLine(model, props.models, facts)}</span>
        </p>
      </div>

      {!running && (
        <div className="engines-local-row-actions">
          {canUse && (
            <Button variant="secondary" size="sm" aria-label={t("engines:local.useLabel", { name })} disabled={choosing || blocked} onClick={() => onUse(model)}>
              {t("engines:local.use")}
            </Button>
          )}
          <Menu label={t("engines:local.moreLabel", { name })}>
            {canReinstall && <MenuItem onSelect={() => onInstall(model)} disabled={blocked}>{t("engines:local.install")}</MenuItem>}
            {present && (
              <>
                <MenuItem onSelect={() => onVerify(model)} disabled={blocked}>{t("engines:local.verify")}</MenuItem>
                <MenuItem tone="danger" onSelect={() => onRemove(model)} disabled={blocked || removal !== null} hint={removal ?? undefined}>
                  {t("engines:local.remove")}
                </MenuItem>
                {removal && <p role="presentation" className="engines-local-menu-note">{removal}</p>}
              </>
            )}
            {(canReinstall || present) && <MenuSeparator />}
            <MenuItem onSelect={() => setDetailsOpen(true)}>{t("engines:local.details.open")}</MenuItem>
          </Menu>
        </div>
      )}

      {running && <JobProgress job={running} name={name} cancelling={cancelling} onCancel={onCancel} />}
      {detailsOpen && <ModelDetails {...props} facts={facts} onClose={() => setDetailsOpen(false)} />}
    </li>
  );
}

function Detail({ term, children }: { term: string; children: ReactNode }) {
  return (
    <div className="engines-local-detail">
      <dt>{term}</dt>
      <dd>{children}</dd>
    </div>
  );
}

export function Warnings({ warnings }: { warnings: readonly string[] }) {
  if (warnings.length === 0) return null;
  return (
    <ul className="engines-local-warnings">
      {warnings.map((warning) => (
        <li key={warning}>{translateIfKnown(`engines:local.warnings.${warning}`) ?? warning}</li>
      ))}
    </ul>
  );
}

/** Everything the row leaves out: state and use, size, engine and memory, speed and accuracy, the check, where a
 * model of the person's own came from, the measured mark and the recommendation, the license and attribution
 * (CC-BY-4.0 asks for it), and the computer. */
function ModelDetails({ model, hardware, recommendation, facts, onClose }: RowProps & { facts: RowFacts; onClose: () => void }) {
  const { t } = useT();
  const { name, state, installed, managed, missingEngine } = facts;
  const size = diskSize(model);
  const inUse = (model.in_use ?? model.in_use_by.length > 0) && model.in_use_by.length > 0;
  const noteKey = modelNoteKey(model);
  const custom = isCustom(model);
  const origin = originOf(model);
  const recommendedHere = recommendation?.model_id === model.id;
  const check = state === "unverified" || state === "corrupt" ? unverifiedText(model)
    : installed && model.verified_by ? t(`engines:local.verifiedBy.${model.verified_by}`) : null;
  const notes: string[] = [];
  if (missingEngine) {
    notes.push(isLocalMode() ? t("engines:local.needsEngineDesktop") : t("engines:local.needsEngine", { command: `bash ${facts.engineCommand}` }));
  }
  const license = model.license ? t("engines:local.license", { license: model.license, attribution: model.attribution ?? "" }).trim() : null;

  return (
    <Dialog title={t("engines:local.details.title", { name })} closeLabel={t("engines:local.details.close")} onClose={onClose}>
      <dl className="engines-local-details">
        {name !== model.id && <Detail term={t("engines:local.details.id")}><code>{model.id}</code></Detail>}
        <Detail term={t("engines:local.details.state")}>
          <p>
            {state === "active" ? `${t("engines:local.states.installed")} · ${t("engines:local.states.active")}` : t(`engines:local.states.${state}`)}
            {model.location === "legacy" && ` · ${t("engines:local.manual")}`}
          </p>
          {inUse && <p>{t("engines:local.inUse", { list: processList(model.in_use_by) })}</p>}
        </Detail>
        {custom && origin && (
          <Detail term={t("engines:local.details.origin")}>
            <p>{t("engines:local.custom.originDetail", { repo: origin.repo, revision: origin.revision })}</p>
          </Detail>
        )}
        {size !== null && <Detail term={t("engines:local.details.size")}><p>{formatBytes(size)}</p></Detail>}
        <Detail term={t("engines:local.details.engine")}>
          <p>
            {managed && installed ? t("engines:local.managedInstalled")
              : model.min_ram_gib > 0 ? t("engines:local.descriptionMinRam", { engine: model.engine, minRam: model.min_ram_gib })
                : t("engines:local.description", { engine: model.engine })}
          </p>
        </Detail>
        {noteKey && <Detail term={t("engines:local.details.speed")}><p>{t(`engines:local.modelNotes.${noteKey}`)}</p></Detail>}
        {check && <Detail term={t("engines:local.details.check")}><p>{check}</p></Detail>}
        {model.kind !== "managed_engine" && !custom && (
          <Detail term={t("engines:local.details.rating")}>
            <p>{`${t(`engines:local.marks.${model.status}`)}. ${t(`engines:local.markHelp.${model.status}`)}`}</p>
            {model.recommended && <p>{t("engines:local.recommended")}</p>}
            {recommendedHere && recommendation && (
              <>
                <p>{reasonText(recommendation, hardware)}</p>
                <Warnings warnings={recommendation.warnings} />
              </>
            )}
          </Detail>
        )}
        {license && <Detail term={t("engines:local.details.license")}><p>{license}</p></Detail>}
        {notes.length > 0 && (
          <Detail term={t("engines:local.details.notes")}>
            {notes.map((note) => <p key={note}>{note}</p>)}
          </Detail>
        )}
        <Detail term={t("engines:local.details.computer")}>
          <p>
            {t("engines:local.hardware", {
              chip: chipName(hardware.arch, hardware.system),
              memory: formatMemory(hardware.memory_gib),
              count: hardware.cores,
              free: formatBytes(hardware.disk_free_bytes),
            })}
          </p>
          <p>{hardware.metal ? t("engines:local.metalYes") : t("engines:local.metalNo")}</p>
        </Detail>
      </dl>
    </Dialog>
  );
}

/** A file that supports the process (voice detection): one line, not a choice. Offers to install it when missing. */
export function SupportLine({ model, job, busy, cancelling, onInstall, onCancel }: RowProps) {
  const { t } = useT();
  const jobRunning = job?.state === "running";
  const running = jobRunning && job.model_id === model.id ? job : null;
  const availability = availabilityOf(model);
  const name = model.id;
  const state = running ? t("engines:local.states.installing") : availability === "installed" ? t("engines:local.states.installed") : availability === "available" ? t("engines:local.states.available") : t("engines:local.states.unverified");
  const canInstall = availability === "available" && !running;
  return (
    <div className="engines-local-support">
      <p className="settings-help">{t("engines:local.auxiliaryLine", { name, state })}</p>
      {canInstall && (
        <Button variant="secondary" size="sm" aria-label={t("engines:local.installLabel", { id: name })} disabled={jobRunning || busy} onClick={() => onInstall(model)}>
          {t("engines:local.install")}
        </Button>
      )}
      {running && <JobProgress job={running} name={name} cancelling={cancelling} onCancel={onCancel} />}
    </div>
  );
}

/** An engine a model runs on (Parakeet's FluidAudio): one line with its state, never a choice or a download. */
export function EngineLine({ process, model }: { process: EngineProcess; model: LocalModel }) {
  const { t } = useT();
  const installed = availabilityOf(model) === "installed";
  const name = translateIfKnown(`engines:local.managedTitle.${process}`) ?? model.id;
  return (
    <div className="engines-local-support">
      <p className="settings-help">
        {t("engines:local.engineLine", { name, state: t(installed ? "engines:local.states.installed" : "engines:local.states.notReady") })}
      </p>
      {!installed && <ManagedHow model={model} />}
    </div>
  );
}

/** How a managed engine gets installed: it comes with Sauri, or (outside the desktop app) the command that installs it. */
export function ManagedHow({ model }: { model: LocalModel }) {
  const { t } = useT();
  const command = model.install?.managed_by ?? model.managed_by;
  if (!isLocalMode() && !command) return null;
  return (
    <p className="settings-help">
      {isLocalMode() ? t("engines:local.managedDesktop") : t("engines:local.managedHow", { command: `bash ${command}` })}
    </p>
  );
}

/** The progress of an install or a check, in words that change only by whole percent, with «Cancelar». */
export function JobProgress({ job, name, cancelling, onCancel }: { job: LocalJob; name: string; cancelling: boolean; onCancel: () => void }) {
  const { t } = useT();
  const percent = percentOf(job);
  const sentence = job.type === "install" ? t("engines:local.installing", { id: name, percent }) : t("engines:local.verifying", { id: name, percent });
  return (
    <div className="engines-local-progress">
      <p role="status">{sentence}</p>
      <ProgressBar label={t("engines:local.progressLabel", { id: name })} value={percent} valueText={`${percent} %`} />
      <p className="settings-help">{t("engines:local.bytes", { done: formatBytes(job.bytes_done), total: formatBytes(job.bytes_total) })}</p>
      <Button variant="secondary" size="sm" aria-label={t("engines:local.cancelLabel", { id: name })} disabled={cancelling} onClick={onCancel}>
        {cancelling ? t("engines:local.cancelling") : t("engines:local.cancel")}
      </Button>
    </div>
  );
}

/** Space needed for an install, in plain words, when it does not fit on the disk; null when it fits. */
export function roomNote(model: LocalModel): string | null {
  const needed = spaceNeeded(model);
  return model.install?.fits_on_disk === false && needed !== null ? t("engines:local.notEnoughSpace", { size: formatBytes(needed) }) : null;
}
