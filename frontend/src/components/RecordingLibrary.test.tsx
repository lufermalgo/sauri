// @vitest-environment jsdom
/**
 * Frontend component tests: meeting list with process states.
 *
 * Feature: meeting-capture-transcription
 * Task: 15.5 — Validates: Requirements 9.1, 9.2, 4.5
 */

import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, cleanup, waitFor, fireEvent } from "@testing-library/react";
import { ProcessState, MeetingOrigin } from "@sauri/shared-types";
import type { MeetingListItem } from "@sauri/shared-types";

import { RecordingLibrary } from "./RecordingLibrary";
import * as api from "../api";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

function meeting(overrides: Partial<MeetingListItem> = {}): MeetingListItem {
  return {
    id: "r-1",
    meetLink: "https://meet.google.com/abc-defg-hij",
    origin: MeetingOrigin.Link,
    processState: ProcessState.Queued,
    failureCause: null,
    createdAt: "2026-10-28T17:45:00Z",
    title: "Synthetic meeting",
    ...overrides,
  };
}

describe("RecordingLibrary — renders the list with process states", () => {
  it("shows each Meeting with its Process_State", async () => {
    vi.spyOn(api, "listMeetings").mockResolvedValue([
      meeting({ id: "r-1", processState: ProcessState.Queued }),
      meeting({ id: "r-2", processState: ProcessState.Completed }),
      meeting({
        id: "r-3",
        processState: ProcessState.Failed,
      }),
    ]);

    render(<RecordingLibrary refreshKey={0} onSelectMeeting={vi.fn()} />);

    await waitFor(() => screen.getByText("Meetings"));

    expect(screen.getByText("Queued")).toBeDefined();
    expect(screen.getByText("Ready")).toBeDefined();
    expect(screen.getByText("Failed")).toBeDefined();
  });

  it("shows title, date, readable state, and an Open action for each meeting", async () => {
    const onSelectMeeting = vi.fn();
    const completedMeeting = meeting({
      id: "r-2",
      processState: ProcessState.Completed,
      title: "Prueba sintetica completa",
    });
    vi.spyOn(api, "listMeetings").mockResolvedValue([
      meeting({ id: "r-1", processState: ProcessState.Recording }),
      completedMeeting,
    ]);

    render(<RecordingLibrary refreshKey={0} onSelectMeeting={onSelectMeeting} />);
    await waitFor(() => screen.getByText("Meetings"));

    expect(screen.getByText("Prueba sintetica completa")).toBeDefined();
    expect(screen.getAllByText(/Oct 28, 2026/).length).toBeGreaterThan(0);
    expect(screen.getByText("Ready")).toBeDefined();
    const buttons = screen.getAllByRole("button", { name: "Open" });
    expect(buttons).toHaveLength(2);
    fireEvent.click(buttons[1]);
    expect(onSelectMeeting).toHaveBeenCalledWith(completedMeeting);
  });

  it("shows the empty-state message when there are no meetings", async () => {
    vi.spyOn(api, "listMeetings").mockResolvedValue([]);

    render(<RecordingLibrary refreshKey={0} onSelectMeeting={vi.fn()} />);
    await waitFor(() => screen.getByText("No meetings registered."));
  });

  it("unauthenticated flow: API error is shown as an alert", async () => {
    vi.spyOn(api, "listMeetings").mockRejectedValue(
      new Error("Not authenticated: token not found")
    );

    render(<RecordingLibrary refreshKey={0} onSelectMeeting={vi.fn()} />);

    const alert = await waitFor(() => screen.getByRole("alert"));
    expect(alert.textContent).toMatch(/Not authenticated/);
  });
});
