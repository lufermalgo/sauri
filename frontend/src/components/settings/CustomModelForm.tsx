import { useId, useState } from "react";
import type { FormEvent } from "react";
import type { CustomInstallRequest, CustomModelProcess, CustomResolveResponse, LocalJob } from "@sauri/shared-types";
import { Button, TextField } from "../ui";
import { resolveCustomModel } from "../../api";
import { formatBytes } from "./engineLabels";
import { JobProgress } from "./LocalModelRow";
import { errorCode, fileName, shortRevision } from "./localModelState";
import { t, translateIfKnown, useT } from "../../i18n";

/** Why a search found nothing to install, in plain words with what to do next. */
function describeResolveError(error: unknown, process: CustomModelProcess): string {
  const code = errorCode(error);
  if (code === "no_compatible_files") return t(`engines:local.custom.errors.no_compatible_files.${process}`);
  // A search refusal first, then the codes every local route shares (the service is down, the registry is unreadable).
  return (code && (translateIfKnown(`engines:local.custom.errors.${code}`) ?? translateIfKnown(`engines:local.errors.${code}`)))
    || t("engines:local.custom.errors.generic");
}

interface CustomModelFormProps {
  process: CustomModelProcess;
  job: LocalJob | null;
  cancelling: boolean;
  busy: boolean;
  onInstall: (request: CustomInstallRequest) => Promise<LocalJob | null>;
  onCancel: () => void;
}

/** «Otro modelo»: a public Hugging Face repository (`owner/repo` or a huggingface.co / hf.co link). The host pins it to
 * one commit and lists the files that fit the process with their size; the person picks one when there are several,
 * sees the license when the repository states it, and installs it like any other model. */
export function CustomModelForm({ process, job, cancelling, busy, onInstall, onCancel }: CustomModelFormProps) {
  const { t } = useT();
  const ids = useId();
  const [source, setSource] = useState("");
  const [searching, setSearching] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [found, setFound] = useState<CustomResolveResponse | null>(null);
  const [chosen, setChosen] = useState<string | null>(null);
  const [startedJob, setStartedJob] = useState<string | null>(null);
  const [starting, setStarting] = useState(false);

  async function search(event: FormEvent) {
    event.preventDefault();
    const value = source.trim();
    setFound(null);
    if (!value) {
      setError(t("engines:local.custom.errors.empty"));
      return;
    }
    setError(null);
    setSearching(true);
    try {
      const answer = await resolveCustomModel(process, value);
      setFound(answer);
      setChosen(answer.files[0]?.path ?? null);
    } catch (failure) {
      setError(describeResolveError(failure, process));
    } finally {
      setSearching(false);
    }
  }

  async function install() {
    if (!found || !chosen) return;
    setStarting(true);
    const started = await onInstall({ process, repo: found.repo, revision: found.revision, file: chosen });
    setStarting(false);
    if (started) setStartedJob(started.id);
  }

  const running = job?.state === "running" && job.id === startedJob ? job : null;
  const otherJob = job?.state === "running" && !running;
  const file = found?.files.find((entry) => entry.path === chosen) ?? null;
  const helpId = `${ids}-help`;

  return (
    <div className="local-custom">
      <form className="local-custom-search" onSubmit={search} noValidate>
        <TextField
          label={t("engines:local.custom.label")}
          value={source}
          placeholder={t("engines:local.custom.placeholder")}
          autoFocus
          autoComplete="off"
          spellCheck={false}
          aria-describedby={helpId}
          error={error ?? undefined}
          onChange={(event) => {
            setSource(event.target.value);
            setFound(null);
            setError(null);
          }}
        />
        <p id={helpId} className="settings-help">
          {t(`engines:local.custom.help.${process}`)} {t("engines:local.custom.public")}
        </p>
        <div>
          <Button type="submit" variant="secondary" size="sm" disabled={searching || running !== null}>
            {searching ? t("engines:local.custom.searching") : t("engines:local.custom.search")}
          </Button>
        </div>
      </form>

      {found && (
        <section className="local-add-section" aria-labelledby={`${ids}-found`}>
          <h3 id={`${ids}-found`} className="settings-group-title">{t("engines:local.custom.foundTitle")}</h3>
          <p>{t("engines:local.custom.found", { repo: found.repo, revision: shortRevision(found.revision) })}</p>
          <p className="settings-help">
            {found.license ? t("engines:local.custom.license", { license: found.license }) : t("engines:local.custom.noLicense")}
          </p>
          {found.files.length > 1 ? (
            <fieldset className="local-custom-files">
              <legend>{t("engines:local.custom.filesLegend")}</legend>
              {found.files.map((entry) => (
                <label key={entry.path} className="local-custom-file">
                  <input
                    type="radio"
                    name={`${ids}-file`}
                    value={entry.path}
                    checked={chosen === entry.path}
                    disabled={running !== null}
                    onChange={() => setChosen(entry.path)}
                  />
                  <span className="local-custom-file-name">{fileName(entry.path)}</span>
                  <span className="engines-local-size">{formatBytes(entry.size)}</span>
                </label>
              ))}
            </fieldset>
          ) : (
            file && <p>{t("engines:local.custom.oneFile", { file: fileName(file.path), size: formatBytes(file.size) })}</p>
          )}
          <p className="settings-help">{t("engines:local.custom.safety")}</p>
          {running ? (
            <JobProgress job={running} name={chosen ? fileName(chosen) : running.model_id} cancelling={cancelling} onCancel={onCancel} />
          ) : (
            file && (
              <div>
                <Button variant="primary" size="sm" disabled={busy || starting || otherJob} onClick={() => void install()}>
                  {t("engines:local.custom.install", { size: formatBytes(file.size) })}
                </Button>
                {otherJob && <p className="settings-help">{t("engines:local.busy")}</p>}
              </div>
            )
          )}
        </section>
      )}
    </div>
  );
}
