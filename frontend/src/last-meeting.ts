/**
 * The recording the user last explored, remembered per device so the portal reopens it at start.
 * Storage can be blocked or throw: then nothing is remembered and nothing is restored.
 */
export const LAST_MEETING_STORAGE_KEY = "sauri_last_meeting_id";

export function readLastMeetingId(): string | null {
  try {
    return localStorage.getItem(LAST_MEETING_STORAGE_KEY) || null;
  } catch {
    return null;
  }
}

export function rememberLastMeeting(meetingId: string): void {
  try {
    if (localStorage.getItem(LAST_MEETING_STORAGE_KEY) !== meetingId) {
      localStorage.setItem(LAST_MEETING_STORAGE_KEY, meetingId);
    }
  } catch {
    // blocked storage: the portal simply starts at the library next time
  }
}

/** Clears the remembered recording, but only when it is `meetingId` (another one may have replaced it). */
export function forgetLastMeeting(meetingId: string): void {
  try {
    if (localStorage.getItem(LAST_MEETING_STORAGE_KEY) === meetingId) {
      localStorage.removeItem(LAST_MEETING_STORAGE_KEY);
    }
  } catch {
    // blocked storage: nothing was remembered
  }
}
