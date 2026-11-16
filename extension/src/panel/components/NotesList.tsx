import React, { useId, useRef, useState } from "react";
import { ExternalLink, RotateCcw, Search } from "lucide-react";
import { Icon } from "../../core/design/Icon";
import { sortNotes } from "../../core/order";
import { formatNoteDate } from "../../core/notes";
import type { NoteDTO, ViewState } from "../../core/types";
import { panelCopy as copy } from "../copy";
import { portalDestination } from "../portal";

export interface NotesListProps {
  state: ViewState;
  notes: NoteDTO[];
  onRetry: () => void;
  onOpenNote: (meetingId: string) => void;
}

function stateLabel(state: string): { label: string; tone: string } {
  if (["completed", "ready", "succeeded"].includes(state)) return { label: copy.ready, tone: "success" };
  if (["failed", "error"].includes(state)) return { label: copy.failed, tone: "error" };
  return { label: state === "queued" ? copy.queued : copy.transcribing, tone: "progress" };
}

export function NotesList({ state, notes, onRetry, onOpenNote }: NotesListProps) {
  const [searching, setSearching] = useState(false);
  const [query, setQuery] = useState("");
  const searchId = useId();
  const searchButton = useRef<HTMLButtonElement>(null);
  const searchAvailable = state === "withData";
  const showSearch = searchAvailable && searching;
  const needle = showSearch ? query.trim().toLocaleLowerCase() : "";
  const visible = sortNotes(notes).filter(note => !needle || (note.title?.trim() || copy.untitled).toLocaleLowerCase().includes(needle));
  const closeSearch = () => { setSearching(false); setQuery(""); searchButton.current?.focus(); };
  return <section className="panel-stack panel-library" aria-labelledby="recordings-heading">
    <div className="panel-row panel-library-heading">
      <h2 id="recordings-heading">{copy.recordings}</h2>
      <div className="panel-row panel-library-tools">
        {searchAvailable && <button ref={searchButton} type="button" className="panel-icon-button" aria-label={copy.search} title={copy.search} aria-expanded={showSearch} aria-controls={searchId} onClick={() => showSearch ? closeSearch() : setSearching(true)}><Icon icon={Search} size={16} /></button>}
        <a href={portalDestination()} target="_blank" rel="noreferrer" className="panel-icon-button" aria-label={copy.portal} title={copy.portal}><Icon icon={ExternalLink} size={16} /></a>
      </div>
    </div>
    {showSearch && <input id={searchId} type="search" autoFocus aria-label={copy.searchField} placeholder={copy.searchField} value={query} onChange={event => setQuery(event.target.value)} onKeyDown={event => { if (event.key === "Escape") closeSearch(); }} />}
    {state === "loading" && <p>{copy.loading}</p>}
    {state === "error" && <div><p role="alert">{copy.listError}</p><button className="panel-with-icon" onClick={onRetry}><Icon icon={RotateCcw} size={16} />{copy.retry}</button></div>}
    {state === "empty" && <p>{copy.empty}</p>}
    {state === "withData" && visible.length === 0 && <p role="status">{copy.noResults}</p>}
    {state === "withData" && visible.length > 0 && <ul className="panel-note-list">{visible.map(note => {
      const status = stateLabel(note.processState);
      return <li className={`panel-note panel-tone-${status.tone}`} key={note.meetingId}>
        <button onClick={() => onOpenNote(note.meetingId)}><strong>{note.title?.trim() || copy.untitled}</strong>{note.createdAt && <span>{formatNoteDate(note.createdAt)}</span>}</button>
        <span className={`panel-badge panel-badge-${status.tone}`}>{status.label}</span>
      </li>;
    })}</ul>}
  </section>;
}
