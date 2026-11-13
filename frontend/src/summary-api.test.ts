// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import { getSummary, getLatestSummaryRequest, getSummaryRequest, requestSummary, listTemplates } from "./api";

const reply = (body: unknown, status = 200) => ({
  ok: status >= 200 && status < 300, status, json: async () => body,
}) as Response;
function stub(body: unknown, status = 200) {
  vi.stubGlobal("localStorage", { getItem: vi.fn().mockReturnValue("synthetic-token"), removeItem: vi.fn() });
  const fetch = vi.fn().mockResolvedValue(reply(body, status));
  vi.stubGlobal("fetch", fetch);
  return fetch;
}
afterEach(() => { vi.unstubAllGlobals(); });

describe("summary and owned-template HTTP adapters", () => {
  it("maps complete snake_case artifact and treats only 404 as absence", async () => {
    const fetch = stub({ summary_id: "sum", meeting_id: "meeting", template_id: "tpl",
      template_name: "Own", template_version: 3, topic: "Literal <text>",
      key_points: ["first", "second"], generation: 4, created_at: "created", updated_at: "updated" });
    await expect(getSummary("meeting")).resolves.toEqual({ summaryId: "sum", meetingId: "meeting",
      templateId: "tpl", templateName: "Own", templateVersion: 3, topic: "Literal <text>",
      keyPoints: ["first", "second"], generation: 4, createdAt: "created", updatedAt: "updated" });
    expect(fetch).toHaveBeenCalledWith(expect.stringContaining("/meetings/meeting/summary"),
      expect.objectContaining({ headers: expect.objectContaining({ Authorization: "Bearer synthetic-token" }) }));
    fetch.mockResolvedValueOnce(reply({}, 404)).mockResolvedValueOnce(reply({}, 503));
    await expect(getSummary("meeting")).resolves.toBeNull();
    await expect(getSummary("meeting")).rejects.toThrow("Error 503");
  });

  it("posts implicit default or explicit owner selection and maps accepted status", async () => {
    const fetch = stub({ event_id: "event", generation: 2, status: "pending" }, 202);
    await expect(requestSummary("meeting", {})).resolves.toEqual({ eventId: "event", generation: 2, status: "pending" });
    expect(JSON.parse(fetch.mock.calls[0][1].body)).toEqual({});
    await requestSummary("meeting", { templateId: "my-tpl" });
    expect(JSON.parse(fetch.mock.calls[1][1].body)).toEqual({ template_id: "my-tpl" });
    expect(fetch.mock.calls[0][1].method).toBe("POST");
  });

  it("distinguishes absent latest from missing event and maps status", async () => {
    const fetch = stub({}, 404);
    await expect(getLatestSummaryRequest("meeting")).resolves.toBeNull();
    await expect(getSummaryRequest("meeting", "missing")).rejects.toThrow("Error 404");
    fetch.mockResolvedValueOnce(reply({ event_id: "event", generation: 5, status: "running" }));
    await expect(getLatestSummaryRequest("meeting")).resolves.toEqual({ eventId: "event", generation: 5, status: "running" });
    fetch.mockResolvedValueOnce(reply({ event_id: "event", generation: 5, status: "succeeded" }));
    await expect(getSummaryRequest("meeting", "event")).resolves.toEqual({ eventId: "event", generation: 5, status: "succeeded" });
    expect(fetch.mock.calls[3][0]).toContain("/summary-requests/event");
  });

  it("maps only server-returned templates including owner, optional category and default", async () => {
    const fetch = stub([{ id: "tpl", owner_user_id: "owner", name: "Own", category_id: null,
      version: 2, instructions: "Opaque <private>", is_default: true, created_at: "c", updated_at: "u" },
      { id: "other", owner_user_id: "owner", name: "Second", category_id: "category",
        version: 1, instructions: "second", is_default: false, created_at: "c", updated_at: "u" }]);
    await expect(listTemplates()).resolves.toEqual([
      { id: "tpl", ownerId: "owner", name: "Own", version: 2, instructions: "Opaque <private>",
        isDefault: true, createdAt: "c", updatedAt: "u" },
      { id: "other", ownerId: "owner", name: "Second", categoryId: "category", version: 1,
        instructions: "second", isDefault: false, createdAt: "c", updatedAt: "u" },
    ]);
    expect(fetch.mock.calls[0][0]).toMatch(/\/api\/v1\/templates$/);
  });
});
