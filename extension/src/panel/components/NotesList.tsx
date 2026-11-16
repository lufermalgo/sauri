import React from "react";
import { ExternalLink, RotateCcw } from "lucide-react";
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
  return <section className="panel-stack panel-library" aria-labelledby="recordings-heading">
    <div className="panel-row panel-library-heading"><h2 id="recordings-heading">{copy.recordings}</h2><a href={portalDestination()} target="_blank" rel="noreferrer" className="panel-with-icon">{copy.portal}<Icon icon={ExternalLink} size={14} /></a></div>
    {state === "loading" && <p>{copy.loading}</p>}
    {state === "error" && <div><p role="alert">{copy.listError}</p><button className="panel-with-icon" onClick={onRetry}><Icon icon={RotateCcw} size={16} />{copy.retry}</button></div>}
    {state === "empty" && <p>{copy.empty}</p>}
    {state === "withData" && <ul className="panel-note-list">{sortNotes(notes).map(note => {
      const status = stateLabel(note.processState);
      return <li className={`panel-note panel-tone-${status.tone}`} key={note.meetingId}>
        <button onClick={() => onOpenNote(note.meetingId)}><strong>{note.title?.trim() || copy.untitled}</strong>{note.createdAt && <span>{formatNoteDate(note.createdAt)}</span>}</button>
        <span className={`panel-badge panel-badge-${status.tone}`}>{status.label}</span>
      </li>;
    })}</ul>}
  </section>;
}
