import { useRef, useState } from "react";
import type { PlaybackManifest } from "../api";
import { transcriptToText, type ExportTurn } from "../transcript-export";
import { downloadMeetingMedia, mediaProgressText, pickMediaSource } from "../media-download";
import { downloadMeetingSummary } from "../summary-download";
import { saveTextFile, transcriptFilename } from "../transcript-download";
import { Download } from "lucide-react";
import { Icon, Menu, MenuItem } from "./ui";
import "../styles/meeting.css";
import { useT } from "../i18n";

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
  const { t } = useT();
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  // A second click while a file is being saved must not open a second file picker.
  const savingMedia = useRef(false);
  const choice = pickMediaSource(manifest);
  const audioOnly = manifest?.video_presence === "absent" || manifest?.video_presence === "unknown";
  const mediaLabel = audioOnly ? t("meeting:downloadAudio") : t("meeting:downloadVideo");

  function downloadTranscript() {
    setError(null);
    try {
      saveTextFile(transcriptFilename(meetingId, title), transcriptToText(turns));
    } catch {
      setError(t("meeting:downloadFailed"));
    }
  }

  async function downloadSummary() {
    setError(null);
    try {
      await downloadMeetingSummary(meetingId, title);
    } catch {
      setError(t("meeting:downloadFailed"));
    }
  }

  async function downloadMedia() {
    if (!choice || savingMedia.current) return;
    savingMedia.current = true;
    setError(null);
    setNotice(mediaProgressText(null));
    try {
      const outcome = await downloadMeetingMedia(meetingId, title, percent => setNotice(mediaProgressText(percent)));
      setNotice(outcome === "opened" ? t("meeting:mediaOpened") : null);
    } catch {
      setNotice(null);
      setError(t("meeting:downloadFailed"));
    } finally {
      savingMedia.current = false;
    }
  }

  return <div className="meeting-downloads">
    <Menu label={t("meeting:download")} tooltip trigger={<Icon icon={Download} />}
      triggerClassName="ui-icon-button ui-icon-button--ghost">
      <MenuItem disabled={!choice} onSelect={() => void downloadMedia()}>{mediaLabel}</MenuItem>
      <MenuItem disabled={!turns.length} onSelect={downloadTranscript}>{t("meeting:downloadTranscript")}</MenuItem>
      <MenuItem disabled={!hasSummary} hint={hasSummary ? undefined : t("meeting:summaryUnavailable")}
        onSelect={() => void downloadSummary()}>{t("meeting:downloadSummary")}</MenuItem>
    </Menu>
    {notice && <p role="status" className="meeting-notice">{notice}</p>}
    {error && <p role="alert" className="meeting-error">{error}</p>}
  </div>;
}
