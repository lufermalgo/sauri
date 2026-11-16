import { useRef, useState } from "react";
import type { PlaybackManifest } from "../api";
import { meeting as text } from "../copy/meeting";
import { transcriptToText, type ExportTurn } from "../transcript-export";
import { downloadMeetingMedia, pickMediaSource } from "../media-download";
import { downloadMeetingSummary } from "../summary-download";
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
  /** A summary exists for this meeting; the download is offered only then. */
  hasSummary?: boolean;
}

export function MeetingDownloads({ meetingId, title, manifest, turns, hasSummary = false }: MeetingDownloadsProps) {
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  // A second click while a file is being saved must not open a second file picker.
  const savingMedia = useRef(false);
  const choice = pickMediaSource(manifest);
  const audioOnly = manifest?.video_presence === "absent" || manifest?.video_presence === "unknown";
  const mediaLabel = audioOnly ? text.downloadAudio : text.downloadVideo;

  function downloadTranscript() {
    setError(null);
    try {
      saveTextFile(transcriptFilename(meetingId, title), transcriptToText(turns));
    } catch {
      setError(text.downloadFailed);
    }
  }

  async function downloadSummary() {
    setError(null);
    try {
      await downloadMeetingSummary(meetingId, title);
    } catch {
      setError(text.downloadFailed);
    }
  }

  async function downloadMedia() {
    if (!choice || savingMedia.current) return;
    savingMedia.current = true;
    setError(null);
    setNotice(text.mediaProgress(null));
    try {
      const outcome = await downloadMeetingMedia(meetingId, title, percent => setNotice(text.mediaProgress(percent)));
      setNotice(outcome === "opened" ? text.mediaOpened : null);
    } catch {
      setNotice(null);
      setError(text.downloadFailed);
    } finally {
      savingMedia.current = false;
    }
  }

  return <div className="meeting-downloads">
    <Menu label={text.download} tooltip trigger={<Icon icon={Download} />}
      triggerClassName="ui-icon-button ui-icon-button--primary">
      <MenuItem disabled={!choice} onSelect={() => void downloadMedia()}>{mediaLabel}</MenuItem>
      <MenuItem disabled={!turns.length} onSelect={downloadTranscript}>{text.downloadTranscript}</MenuItem>
      <MenuItem disabled={!hasSummary} hint={hasSummary ? undefined : text.summaryUnavailable}
        onSelect={() => void downloadSummary()}>{text.downloadSummary}</MenuItem>
    </Menu>
    {notice && <p role="status" className="meeting-notice">{notice}</p>}
    {error && <p role="alert" className="meeting-error">{error}</p>}
  </div>;
}
