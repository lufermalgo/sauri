// @vitest-environment jsdom
/**
 * Frontend component tests: meeting list with process states.
 *
 * Feature: meeting-capture-transcription
 * Task: 15.5 — Validates: Requirements 9.1, 9.2, 4.5
 */

import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, cleanup, waitFor } from "@testing-library/react";
import { FailureCause, ProcessState, MeetingOrigin } from "@sauri/shared-types";
import type { Meeting } from "@sauri/shared-types";

import { MeetingList } from "./MeetingList";
import * as api from "../api";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

function meeting(overrides: Partial<Meeting> = {}): Meeting {
  return {
    id: "r-1",
    meetLink: "https://meet.google.com/abc-defg-hij",
    origin: MeetingOrigin.Link,
    processState: ProcessState.Queued,
    failureCause: undefined,
    createdBy: "test-user",
    createdAt: new Date().toISOString(),
    ...overrides,
  };
}

describe("MeetingList — renders the list with process states", () => {
  it("shows each Meeting with its Process_State", async () => {
    vi.spyOn(api, "listMeetings").mockResolvedValue([
      meeting({ id: "r-1", processState: ProcessState.Queued }),
      meeting({ id: "r-2", processState: ProcessState.Completed }),
      meeting({
        id: "r-3",
        processState: ProcessState.Failed,
        failureCause: FailureCause.EngineFailure,
      }),
    ]);

    render(<MeetingList refreshKey={0} onSelectMeeting={vi.fn()} />);

    await waitFor(() => screen.getByText("Meetings"));

    expect(screen.getAllByText(ProcessState.Queued).length).toBeGreaterThan(0);
    expect(screen.getAllByText(ProcessState.Completed).length).toBeGreaterThan(0);
    expect(screen.getAllByText(ProcessState.Failed).length).toBeGreaterThan(0);
    expect(screen.getByText(FailureCause.EngineFailure)).toBeDefined();
  });

  it("only shows the 'View transcript' button for completed meetings", async () => {
    vi.spyOn(api, "listMeetings").mockResolvedValue([
      meeting({ id: "r-1", processState: ProcessState.Recording }),
      meeting({ id: "r-2", processState: ProcessState.Completed }),
    ]);

    render(<MeetingList refreshKey={0} onSelectMeeting={vi.fn()} />);
    await waitFor(() => screen.getByText("Meetings"));

    const buttons = screen.getAllByRole("button", { name: /View transcript/i });
    expect(buttons).toHaveLength(1);
  });

  it("shows the empty-state message when there are no meetings", async () => {
    vi.spyOn(api, "listMeetings").mockResolvedValue([]);

    render(<MeetingList refreshKey={0} onSelectMeeting={vi.fn()} />);
    await waitFor(() => screen.getByText("No meetings registered."));
  });

  it("unauthenticated flow: API error is shown as an alert", async () => {
    vi.spyOn(api, "listMeetings").mockRejectedValue(
      new Error("Not authenticated: token not found")
    );

    render(<MeetingList refreshKey={0} onSelectMeeting={vi.fn()} />);

    const alert = await waitFor(() => screen.getByRole("alert"));
    expect(alert.textContent).toMatch(/Not authenticated/);
  });
});
