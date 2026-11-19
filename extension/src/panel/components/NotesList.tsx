import React, { useEffect, useId, useRef, useState } from "react";
import { ExternalLink, RotateCcw, Search } from "lucide-react";
import { Icon } from "../../core/design/Icon";
import { sortNotes } from "../../core/order";
import { formatNoteDate } from "../../core/notes";
import type { NoteDTO, ViewState } from "../../core/types";
import { useT, type TranslateFn } from "../../i18n";
import { portalDestination } from "../portal";

export interface NotesListProps {
  state: ViewState;
  notes: NoteDTO[];
  onRetry: () => void;
  onOpenNote: (meetingId: string) => void;
}

function stateLabel(state: string, t: TranslateFn): { label: string; tone: string } {
  if (["completed", "ready", "succeeded"].includes(state)) return { label: t("panel:ready"), tone: "success" };
  if (["failed", "error"].includes(state)) return { label: t("panel:failed"), tone: "error" };
  return { label: state === "queued" ? t("panel:queued") : t("panel:transcribing"), tone: "progress" };
}

/** The portal's address once the app is found; the link stays hidden while no Sauri app answers. */
function usePortalLink(state: ViewState): string | null {
  const [portal, setPortal] = useState<string | null>(null);
  useEffect(() => {
    let cancelled = false;
    portalDestination().then(url => { if (!cancelled) setPortal(url); }, () => { if (!cancelled) setPortal(null); });
    return () => { cancelled = true; };
  }, [state]);
  return portal;
}

export function NotesList({ state, notes, onRetry, onOpenNote }: NotesListProps) {
  const { t, i18n } = useT();
  const [searching, setSearching] = useState(false);
  const [query, setQuery] = useState("");
  const searchId = useId();
  const searchButton = useRef<HTMLButtonElement>(null);
  const portal = usePortalLink(state);
  const searchAvailable = state === "withData";
  const showSearch = searchAvailable && searching;
  const needle = showSearch ? query.trim().toLocaleLowerCase(i18n.language) : "";
  const visible = sortNotes(notes).filter(note => !needle || (note.title?.trim() || t("panel:untitled")).toLocaleLowerCase(i18n.language).includes(needle));
  const closeSearch = () => { setSearching(false); setQuery(""); searchButton.current?.focus(); };
  return <section className="panel-stack panel-library" aria-labelledby="recordings-heading">
    <div className="panel-row panel-library-heading">
      <h2 id="recordings-heading">{t("panel:recordings")}</h2>
      <div className="panel-row panel-library-tools">
        {searchAvailable && <button ref={searchButton} type="button" className="panel-icon-button" aria-label={t("panel:search")} title={t("panel:search")} aria-expanded={showSearch} aria-controls={searchId} onClick={() => showSearch ? closeSearch() : setSearching(true)}><Icon icon={Search} size={16} /></button>}
        {portal && <a href={portal} target="_blank" rel="noreferrer" className="panel-icon-button" aria-label={t("panel:portal")} title={t("panel:portal")}><Icon icon={ExternalLink} size={16} /></a>}
      </div>
    </div>
    {showSearch && <input id={searchId} type="search" autoFocus aria-label={t("panel:searchField")} placeholder={t("panel:searchField")} value={query} onChange={event => setQuery(event.target.value)} onKeyDown={event => { if (event.key === "Escape") closeSearch(); }} />}
    {state === "loading" && <p>{t("panel:loading")}</p>}
    {state === "error" && <div><p role="alert">{t("panel:listError")}</p><button className="panel-with-icon" onClick={onRetry}><Icon icon={RotateCcw} size={16} />{t("panel:retry")}</button></div>}
    {state === "empty" && <p>{t("panel:empty")}</p>}
    {state === "withData" && visible.length === 0 && <p role="status">{t("panel:noResults")}</p>}
    {state === "withData" && visible.length > 0 && <ul className="panel-note-list">{visible.map(note => {
      const status = stateLabel(note.processState, t);
      return <li className={`panel-note panel-tone-${status.tone}`} key={note.meetingId}>
        <button onClick={() => onOpenNote(note.meetingId)}><strong>{note.title?.trim() || t("panel:untitled")}</strong>{note.createdAt && <span>{formatNoteDate(note.createdAt, i18n.language)}</span>}</button>
        <span className={`panel-badge panel-badge-${status.tone}`}>{status.label}</span>
      </li>;
    })}</ul>}
  </section>;
}
