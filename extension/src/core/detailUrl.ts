// Detail View URL — Req. 6.2
const PARAM_MEETING_ID = "meetingId";

/** Builds the relative URL for detail/index.html with the meeting_id as a query param (Req. 6.2) */
export function buildDetailUrl(meetingId: string): string {
  const params = new URLSearchParams({ [PARAM_MEETING_ID]: meetingId });
  return `src/detail/index.html?${params.toString()}`;
}

/** Reads the meeting_id from a detail.html URL; null if absent (Req. 6.2, 6.5) */
export function readMeetingId(url: string): string | null {
  try {
    const parsed = new URL(url, "http://localhost/");
    return parsed.searchParams.get(PARAM_MEETING_ID);
  } catch {
    return null;
  }
}
