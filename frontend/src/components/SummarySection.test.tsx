// @vitest-environment jsdom
/** T19/#287 RED — R1/P2/P5 and design §7 summary lifecycle.
 * Synthetic API seam; does not certify HTTP mapping, provider execution or accuracy.
 * Copy/download actions belong to T21; serialization/default fallback remain unspecified.
 */
import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import type { MeetingSummary, SummaryRequestStatus, SummaryTemplate } from "@sauri/shared-types";
import { SummarySection } from "./SummarySection";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({
  getSummary: vi.fn(), getLatestSummaryRequest: vi.fn(), getSummaryRequest: vi.fn(),
  requestSummary: vi.fn(), listTemplates: vi.fn(),
}));
vi.mock("../api", () => api);

const meetingId = "synthetic-meeting";
const timestamp = "2026-11-13T00:00:00Z";
const summary: MeetingSummary = {
  summaryId: "summary-one", meetingId, templateId: "template-own", templateName: "Agreements",
  templateVersion: 1, topic: "A synthetic topic <literal>",
  keyPoints: ["First point & its details", "Second point: do not reorder"],
  generation: 1, createdAt: timestamp, updatedAt: timestamp,
};
const personal: SummaryTemplate = {
  id: summary.templateId, ownerId: "synthetic-owner", name: summary.templateName, version: 1,
  instructions: "Opaque private instructions", isDefault: true, createdAt: timestamp, updatedAt: timestamp,
};
const pending: SummaryRequestStatus = { eventId: "event-two", generation: 2, status: "pending" };
const neutral = /No summary available for this meeting yet\./i;

// Static import now that T20 supplies the production component; RED commit remains in history.
async function openSection(hasTranscript = true) {
  await act(async () => { render(<SummarySection meetingId={meetingId} hasTranscript={hasTranscript} />); });
}
async function poll() {
  await act(async () => { await vi.advanceTimersByTimeAsync(3000); });
}
async function request() {
  await act(async () => {
    fireEvent.click(screen.getByRole("button", { name: /(?:request|generate|create).*summary/i }));
  });
}
function expectContent(value: MeetingSummary = summary) {
  expect(screen.getByText(value.topic, { exact: true }).textContent).toBe(value.topic);
  for (const point of value.keyPoints) expect(screen.getByText(point, { exact: true }).textContent).toBe(point);
}

beforeEach(() => {
  vi.resetAllMocks();
  vi.useFakeTimers();
  api.getSummary.mockResolvedValue(summary);
  api.getLatestSummaryRequest.mockResolvedValue(null);
  api.listTemplates.mockResolvedValue([personal]);
  api.requestSummary.mockResolvedValue(pending);
  api.getSummaryRequest.mockResolvedValue({ ...pending, status: "running" });
});
afterEach(() => { cleanup(); vi.useRealTimers(); });

describe("summary presentation and durable status (T19 RED)", () => {
  it("has its own accessible section with topic and ordered, unchanged key points", async () => {
    await openSection();
    const section = screen.getByRole("region", { name: /summary/i });
    expect(within(section).getByText(summary.topic, { exact: true })).toBeDefined();
    const points = within(section).getAllByRole("listitem").map((item) => item.textContent);
    expect(points).toEqual(summary.keyPoints);
    expectContent();
    expect(screen.queryByText(personal.instructions)).toBeNull();
    expect(api.getSummary).toHaveBeenCalledWith(meetingId);
    expect(api.getLatestSummaryRequest).toHaveBeenCalledWith(meetingId);
  });

  it("shows a neutral empty state only when summary is 404 and no accepted request exists", async () => {
    api.getSummary.mockRejectedValue(new Error("Error 404: Summary not available"));
    await openSection();
    expect(screen.getByText(neutral)).toBeDefined();
    expect(api.requestSummary).not.toHaveBeenCalled(); // no generation on mount/transcript commit
    await poll();
    expect(api.getSummaryRequest).not.toHaveBeenCalled();
  });

  it.each(["pending", "running"] as const)("resumes latest %s request without treating 404 as failure", async (status) => {
    api.getSummary.mockRejectedValue(new Error("Error 404: Summary not available"));
    api.getLatestSummaryRequest.mockResolvedValue({ ...pending, status });
    await openSection();
    expect(screen.queryByText(neutral)).toBeNull();
    expect(screen.getByText(new RegExp(status, "i"))).toBeDefined();
    expect(api.requestSummary).not.toHaveBeenCalled();
    await poll();
    expect(api.getSummaryRequest).toHaveBeenCalledWith(meetingId, pending.eventId);
  });

  it("surfaces a summary fetch error instead of calling it a neutral absence", async () => {
    api.getSummary.mockRejectedValue(new Error("Error 503: unavailable"));
    await openSection();
    expect(screen.queryByText(neutral)).toBeNull();
    expect(screen.getByText(/(?:unable|could not|failed|error).*summary|summary.*(?:unavailable|error)/i)).toBeDefined();
  });

  it("requests with the configured default and polls the returned event only after acceptance", async () => {
    await openSection();
    expect(api.listTemplates).toHaveBeenCalled();
    expect(screen.getByRole("option", { name: /Agreements.*default|default.*Agreements/i })).toBeDefined();
    expect(api.requestSummary).not.toHaveBeenCalled();
    await request();
    expect(api.requestSummary).toHaveBeenCalledTimes(1);
    expect(api.requestSummary.mock.calls[0][0]).toBe(meetingId);
    const input = api.requestSummary.mock.calls[0][1] as { templateId?: string } | undefined;
    expect(input?.templateId).toBeUndefined(); // API resolves the configured default
    await poll();
    expect(api.getSummaryRequest).toHaveBeenCalledWith(meetingId, pending.eventId);
    expectContent();
  });

  it("refreshes successful content after polling succeeds and stops polling the terminal event", async () => {
    const next: MeetingSummary = { ...summary, summaryId: "summary-two", generation: 2,
      topic: "New successful topic", keyPoints: ["New first point", "New second point"] };
    api.getLatestSummaryRequest.mockResolvedValue(pending);
    api.getSummary.mockResolvedValueOnce(summary).mockResolvedValue(next);
    api.getSummaryRequest.mockResolvedValue({ ...pending, status: "succeeded" });
    await openSection();
    await poll();
    expect(api.getSummary.mock.calls.length).toBeGreaterThanOrEqual(2);
    expectContent(next);
    expect(screen.queryByText(summary.topic, { exact: true })).toBeNull();
    const count = api.getSummaryRequest.mock.calls.length;
    await poll();
    expect(api.getSummaryRequest).toHaveBeenCalledTimes(count);
  });

  it("keeps the old successful artifact on terminal failure without exposing provider details", async () => {
    api.getLatestSummaryRequest.mockResolvedValue(pending);
    api.getSummaryRequest.mockResolvedValue({ ...pending, status: "failed", error: "private provider trace" });
    await openSection();
    await poll();
    expectContent();
    expect(screen.getByText(/(?:generation|summary).*(?:failed|could not)|(?:failed|could not).*summary/i)).toBeDefined();
    expect(screen.queryByText(/private provider trace/i)).toBeNull();
    expect(screen.queryByText(neutral)).toBeNull();
    const count = api.getSummaryRequest.mock.calls.length;
    await poll();
    expect(api.getSummaryRequest).toHaveBeenCalledTimes(count);
  });

  it("retries status after a network error without conflating it with generation failure", async () => {
    api.getLatestSummaryRequest.mockResolvedValue(pending);
    api.getSummaryRequest.mockRejectedValueOnce(new Error("private provider trace"))
      .mockResolvedValue({ ...pending, status: "running" });
    await openSection();
    await poll();
    expectContent();
    expect(screen.queryByText(/private provider trace/i)).toBeNull();
    expect(screen.queryByText(/generation failed/i)).toBeNull();
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: /retry.*status|status.*retry/i })); });
    expect(api.getSummaryRequest.mock.calls.length).toBeGreaterThanOrEqual(2);
    expect(screen.getByText(/running/i)).toBeDefined();
    await poll();
    expect(api.getSummaryRequest.mock.calls.length).toBeGreaterThanOrEqual(3);
  });

  it("does not invent a default when none is configured; explicit selection sends its id", async () => {
    api.listTemplates.mockResolvedValue([{ ...personal, isDefault: false }]);
    await openSection();
    expect(screen.getByRole("button", { name: /request summary/i }).hasAttribute("disabled")).toBe(true);
    expect(api.requestSummary).not.toHaveBeenCalled();
    await act(async () => {
      fireEvent.change(screen.getByLabelText("Template"), { target: { value: personal.id } });
    });
    await request();
    expect(api.requestSummary).toHaveBeenCalledWith(meetingId, { templateId: personal.id });
  });

  it("does not offer a request until a transcript exists", async () => {
    await openSection(false);
    expect(screen.queryByRole("button", { name: /request summary/i })).toBeNull();
  });

  it("cancels polling when unmounted", async () => {
    api.getLatestSummaryRequest.mockResolvedValue(pending);
    await openSection();
    cleanup();
    const count = api.getSummaryRequest.mock.calls.length;
    await poll();
    expect(api.getSummaryRequest).toHaveBeenCalledTimes(count);
  });
});
