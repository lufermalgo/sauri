import { Pause, Play } from "lucide-react";
import type { SpeakerDisposition } from "../api";
import { copy } from "../copy/es";
import type { ListeningInterval } from "../speaker-review-interval";
import { Avatar, Button, Icon, TextField, useTooltip } from "./ui";

export interface SpeakerRowModel {
  speakerId: string;
  label: string;
  initials: string;
  color: string;
  disposition: SpeakerDisposition | null;
  interval: ListeningInterval | null;
}

interface SpeakerReviewPanelProps {
  rows: SpeakerRowModel[];
  complete: boolean;
  selectedId: string | undefined;
  names: Record<string, string>;
  busyId: string | null;
  playingId: string | null;
  playbackReady: boolean;
  playbackLoading: boolean;
  error: string | null;
  onSelect: (speakerId: string) => void;
  onNameChange: (speakerId: string, name: string) => void;
  onListen: (row: SpeakerRowModel) => void;
  onSubmit: (speakerId: string, disposition: SpeakerDisposition, label?: string) => void;
}

const text = copy.speakerReview;

/** Speaker identification list shown inside the review dialog: one row per speaker. */
export function SpeakerReviewPanel({
  rows, complete, selectedId, names, busyId, playingId, playbackReady, playbackLoading, error,
  onSelect, onNameChange, onListen, onSubmit,
}: SpeakerReviewPanelProps) {
  return <div className="meeting-speaker-review">
    <p role="status" className="meeting-sr-only">{complete ? text.complete : text.pending}</p>
    {error && <p role="alert" className="meeting-error">{error}</p>}
    {rows.map(row => <SpeakerRow key={row.speakerId} row={row} selected={selectedId === row.speakerId}
      name={names[row.speakerId] ?? ""} busy={busyId === row.speakerId} playing={playingId === row.speakerId}
      playbackReady={playbackReady} playbackLoading={playbackLoading}
      onSelect={onSelect} onNameChange={onNameChange} onListen={onListen} onSubmit={onSubmit} />)}
  </div>;
}

interface SpeakerRowProps extends Pick<SpeakerReviewPanelProps, "playbackReady" | "playbackLoading" | "onSelect" | "onNameChange" | "onListen" | "onSubmit"> {
  row: SpeakerRowModel;
  selected: boolean;
  name: string;
  busy: boolean;
  playing: boolean;
}

function SpeakerRow({ row, selected, name, busy, playing, playbackReady, playbackLoading, onSelect, onNameChange, onListen, onSubmit }: SpeakerRowProps) {
  const { speakerId, label, interval } = row;
  const trimmed = name.trim();
  const listenName = playing ? text.stopFor(label) : text.listenTo(label);
  const tip = useTooltip(listenName);
  return <article className="meeting-review-item" aria-busy={busy || undefined}>
    <div className="meeting-review-row">
      <Avatar initials={row.initials} color={row.color} size="md" />
      <div className="meeting-review-identity">
        <h4><button type="button" className="meeting-speaker-select"
          aria-label={text.selectSpeaker(label)} aria-expanded={selected}
          aria-controls={`speaker-editor-${speakerId}`}
          onClick={() => onSelect(speakerId)}>{label}</button></h4>
        <span className={row.disposition === null ? "meeting-review-pending" : "meeting-review-confirmed"}>
          {row.disposition === null ? text.pendingState : text.confirmedState}
        </span>
      </div>
      <span className="meeting-review-listen">
        <Button variant="secondary" aria-label={listenName} {...tip.triggerProps}
          onClick={() => { tip.hide(); onListen(row); }}
          disabled={!interval || !playbackReady}>
          <Icon icon={playing ? Pause : Play} size={16} />
          {playing ? text.stop : text.listen}
        </Button>
        {tip.tooltip}
      </span>
    </div>
    {!interval && <p>{text.noInterval}</p>}
    {interval?.short && <p>{text.shortInterval}</p>}
    {interval && !playbackReady && !playbackLoading && <p>{text.playbackUnavailable}</p>}
    {selected && <div className="meeting-review-editor" id={`speaker-editor-${speakerId}`}>
      <div className="meeting-review-name">
        <TextField label={text.nameFor(label)} id={`speaker-name-${speakerId}`} type="text" value={name}
          onChange={event => onNameChange(speakerId, event.target.value)} disabled={busy} />
        <Button variant="primary" aria-label={text.saveNameFor(label)} disabled={busy || !trimmed}
          onClick={() => onSubmit(speakerId, "named", trimmed)}>{text.saveName}</Button>
      </div>
      <div className="meeting-review-decision">
        <Button variant="secondary" aria-label={text.confirmFor(label)} disabled={busy}
          onClick={() => onSubmit(speakerId, "confirmed")}>{text.confirm}</Button>
        <Button variant="secondary" aria-label={text.correctFor(label)} disabled={busy || !trimmed}
          onClick={() => onSubmit(speakerId, "corrected", trimmed)}>{text.correct}</Button>
        {busy && <span role="status">{text.saving}</span>}
      </div>
    </div>}
  </article>;
}
