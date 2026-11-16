import { useState } from "react";
import type { PlaybackManifest } from "../api";
import { meeting as text } from "../copy/meeting";
import { transcriptToText, type ExportTurn } from "../transcript-export";
import { saveTextFile, transcriptFilename } from "../transcript-download";
import { Download } from "lucide-react";
import { Icon, Menu, MenuItem } from "./ui";
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
      saveTextFile(transcriptFilename(meetingId, title), transcriptToText(turns));
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
    <Menu label={text.download} tooltip trigger={<Icon icon={Download} />}
      triggerClassName="ui-icon-button ui-icon-button--primary">
      <MenuItem disabled={!source?.url} onSelect={downloadMedia}>{mediaLabel}</MenuItem>
      <MenuItem disabled={!turns.length} onSelect={downloadTranscript}>{text.downloadTranscript}</MenuItem>
    </Menu>
    {error && <p role="alert" className="meeting-error">{text.downloadFailed}</p>}
  </div>;
}
