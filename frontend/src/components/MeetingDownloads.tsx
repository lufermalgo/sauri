import { useState } from "react";
import type { PlaybackManifest } from "../api";
import { meeting as text } from "../copy/meeting";
import { titleToFilename } from "../download-filename";
import { transcriptToText, type ExportTurn } from "../transcript-export";
import { Menu, MenuItem } from "./ui";
import "../styles/meeting.css";

export interface MeetingDownloadsProps {
  meetingId: string;
  /** Current meeting title (including a rename not yet reflected by the parent). */
  title?: string | null;
  manifest: PlaybackManifest | null;
  turns: ExportTurn[];
}

export function MeetingDownloads({ meetingId, title, manifest, turns }: MeetingDownloadsProps) {
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
      link.download = titleToFilename(title, "txt") ?? text.transcriptFilename(meetingId);
      document.body.append(link);
      link.click();
      link.remove();
      // Give the browser time to start reading the download before releasing it.
      setTimeout(() => URL.revokeObjectURL(url), 0);
    } catch {
      setError(true);
    }
  }

  function downloadMedia() {
    if (!source?.url) return;
    setError(false);
    const link = document.createElement("a");
    link.href = source.url;
    link.download = "";
    document.body.append(link);
    link.click();
    link.remove();
  }

  return <div className="meeting-downloads">
    <Menu label={text.download} triggerLabel={text.download} triggerVariant="primary">
      <MenuItem disabled={!source?.url} onSelect={downloadMedia}>{mediaLabel}</MenuItem>
      <MenuItem disabled={!turns.length} onSelect={downloadTranscript}>{text.downloadTranscript}</MenuItem>
    </Menu>
    {error && <p role="alert" className="meeting-error">{text.downloadFailed}</p>}
  </div>;
}
