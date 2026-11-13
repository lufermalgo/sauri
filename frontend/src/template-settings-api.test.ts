// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createCategory, createTemplate, listCategories, setDefaultTemplate, updateTemplate } from "./api";

const template = {
  id: "tpl-one", owner_user_id: "owner", name: "Personal", instructions: " \n{opaque}  ",
  category_id: null, version: 2, is_default: false,
  created_at: "2026-11-13T00:00:00Z", updated_at: "2026-11-13T00:00:00Z",
};
const category = { id: "cat-one", owner_user_id: "owner", name: "Projects", created_at: "2026-11-13T00:00:00Z" };
let fetchStub: ReturnType<typeof vi.fn>;

beforeEach(() => {
  const values = new Map<string, string>([["sauri_token", "synthetic-test-token"]]);
  vi.stubGlobal("localStorage", {
    getItem: (key: string) => values.get(key) ?? null,
    setItem: (key: string, value: string) => { values.set(key, value); },
    removeItem: (key: string) => { values.delete(key); },
  });
  fetchStub = vi.fn();
  vi.stubGlobal("fetch", fetchStub);
});
afterEach(() => { vi.unstubAllGlobals(); });

function reply(value: unknown, status = 200) {
  fetchStub.mockResolvedValueOnce({ ok: status >= 200 && status < 300, status, json: async () => value });
}
function request() {
  const [url, init] = fetchStub.mock.calls.at(-1) as [string, RequestInit];
  expect(init.headers).toMatchObject({ Authorization: "Bearer synthetic-test-token" });
  return { url, method: init.method, body: JSON.parse(init.body as string) as Record<string, unknown> };
}

describe("settings API maps authenticated personal template/category contracts", () => {
  it("creates template with opaque instructions and optional category", async () => {
    reply(template, 201);
    expect(await createTemplate({ name: "Personal", instructions: template.instructions })).toMatchObject({
      id: "tpl-one", ownerId: "owner", instructions: template.instructions, isDefault: false, version: 2,
    });
    expect(request()).toMatchObject({ method: "POST", body: { name: "Personal", instructions: template.instructions } });
    expect(request().url).toMatch(/\/api\/v1\/templates$/);
    expect(request().body).not.toHaveProperty("category_id");
  });

  it("PATCH preserves field presence: omitted category vs explicit null", async () => {
    reply(template);
    await updateTemplate("tpl/one", { instructions: "\nNew raw text " });
    expect(request().url).toMatch(/\/templates\/tpl%2Fone$/);
    expect(request()).toMatchObject({ method: "PATCH", body: { instructions: "\nNew raw text " } });
    expect(request().body).not.toHaveProperty("category_id");
    reply(template);
    await updateTemplate("tpl-one", { categoryId: null });
    expect(request().body).toEqual({ category_id: null });
    reply({ ...template, category_id: "cat-one" });
    expect(await updateTemplate("tpl-one", { categoryId: "cat-one" })).toMatchObject({ categoryId: "cat-one" });
    expect(request().body).toEqual({ category_id: "cat-one" });
  });

  it("maps only caller categories and creates one without changing its name", async () => {
    reply([category]);
    expect(await listCategories()).toEqual([{ id: category.id, ownerId: "owner", name: "Projects", createdAt: category.created_at }]);
    expect(fetchStub.mock.calls[0][0]).toMatch(/\/templates\/categories$/);
    reply(category, 201);
    expect(await createCategory("Projects")).toMatchObject({ ownerId: "owner", name: "Projects" });
    expect(request()).toMatchObject({ method: "POST", body: { name: "Projects" } });
  });

  it("consumes 204 default setter without parsing a body and surfaces denial", async () => {
    fetchStub.mockResolvedValueOnce({ ok: true, status: 204, json: () => { throw Error("204 must not parse JSON"); } });
    await expect(setDefaultTemplate("tpl-one")).resolves.toBeUndefined();
    expect(request()).toMatchObject({ method: "PUT", body: { template_id: "tpl-one" } });
    expect(request().url).toMatch(/\/templates\/default$/);
    reply({}, 422);
    await expect(setDefaultTemplate("other-owner-template")).rejects.toThrow("Error 422");
  });

  it("invalidates stale credentials on unauthorized default selection", async () => {
    reply({}, 401);
    await expect(setDefaultTemplate("tpl-one")).rejects.toThrow("Error 401");
    expect(localStorage.getItem("sauri_token")).toBeNull();
  });
});
