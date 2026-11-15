import { useState } from "react";
import type { PlaybackManifest } from "../api";
import { meeting as text } from "../copy/meeting";
import { transcriptToText, type ExportTurn } from "../transcript-export";
import { Button } from "./ui";
import "../styles/meeting.css";

export interface MeetingDownloadsProps {
  meetingId: string;
  manifest: PlaybackManifest | null;
  turns: ExportTurn[];
}

export function MeetingDownloads({ meetingId, manifest, turns }: MeetingDownloadsProps) {
  const [error, setError] = useState(false);
  const audioOnly = manifest?.video_presence === "absent" || manifest?.video_presence === "unknown";
  const source = audioOnly ? manifest?.audio_source : manifest?.video_presence === "muxed"
    ? manifest.muxed_video_source : manifest?.video_sources[0];
  const mediaLabel = audioOnly ? text.downloadAudio : text.downloadVideo;

  function downloadTranscript() {
    setError(false);
    try {
      const url = URL.createObjectURL(new Blob([transcriptToText(turns)], { type: "text/plain;charset=utf-8" }));
      const link = document.createElement("a");
      link.href = url;
      link.download = text.transcriptFilename(meetingId);
      document.body.append(link);
      link.click();
      link.remove();
      // Give the browser time to start reading the download before releasing it.
      setTimeout(() => URL.revokeObjectURL(url), 0);
    } catch {
      setError(true);
    }
  }

  return <div className="meeting-downloads">
    {source?.url ? <a className="ui-button ui-button--secondary" href={source.url} download>{mediaLabel}</a>
      : <Button variant="secondary" disabled>{mediaLabel}</Button>}
    <Button variant="secondary" disabled={!turns.length} onClick={downloadTranscript}>{text.downloadTranscript}</Button>
    {error && <p role="alert" className="meeting-error">{text.downloadFailed}</p>}
  </div>;
}
