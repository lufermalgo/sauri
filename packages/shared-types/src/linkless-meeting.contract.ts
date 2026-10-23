import { CaptureOrigin, Meeting, MeetingOrigin, ProcessState } from "./index.js";

const linklessMeeting: Meeting = {
  id: "synthetic-meeting-id",
  meetLink: null,
  origin: MeetingOrigin.Manual,
  processState: ProcessState.Queued,
  createdBy: "synthetic-user-id",
  createdAt: "2026-01-01T00:00:00Z",
};

const webUploadOrigin: CaptureOrigin = CaptureOrigin.WebUpload;

void linklessMeeting;
void webUploadOrigin;
