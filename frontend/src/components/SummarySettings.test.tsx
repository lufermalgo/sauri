// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import "@testing-library/jest-dom/vitest";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { answerEnginesApi } from "./engineApiStub";
import { SummarySettings } from "./settings/SummarySettings";
import { t } from "../i18n";

interface FakeTemplate {
  id: string;
  name: string;
  instructions: string;
  owner_user_id: string;
  category_id: string | null;
  version: number;
  is_default: boolean;
  provenance: string | null;
  created_at: string;
  updated_at: string;
}

function template(overrides: Partial<FakeTemplate> & Pick<FakeTemplate, "id" | "name">): FakeTemplate {
  return {
    instructions: `Instructions of ${overrides.name}`,
    owner_user_id: "u1",
    category_id: null,
    version: 1,
    is_default: false,
    provenance: null,
    created_at: "2026-11-01T10:00:00+00:00",
    updated_at: "2026-11-01T10:00:00+00:00",
    ...overrides,
  };
}

interface Call { method: string; path: string; body: Record<string, unknown> | null }

/** A tiny in-memory stand-in for /api/v1/templates; `failing` makes a "METHOD path" answer 500. */
function fakeBackend(initial: { templates: FakeTemplate[]; categories: { id: string; name: string }[] }) {
  const templates = [...initial.templates];
  const categories = initial.categories.map((category) => ({ ...category, owner_user_id: "u1", created_at: "2026-11-01T10:00:00+00:00" }));
  const calls: Call[] = [];
  const failing = new Set<string>();
  const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status });

  const handler = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = new URL(String(input));
    const engines = answerEnginesApi(url.pathname);
    if (engines) return engines;
    const method = init?.method ?? "GET";
    const path = url.pathname.replace("/api/v1/templates", "") || "/";
    const body = init?.body ? (JSON.parse(String(init.body)) as Record<string, unknown>) : null;
    calls.push({ method, path, body });
    if (failing.has(`${method} ${path}`)) return json({ detail: "boom" }, 500);

    if (method === "GET" && path === "/") return json(templates);
    if (method === "GET" && path === "/categories") return json(categories);
    if (method === "POST" && path === "/categories") {
      const created = { id: `c${categories.length + 1}`, name: String(body?.name), owner_user_id: "u1", created_at: "2026-11-02T10:00:00+00:00" };
      categories.push(created);
      return json(created, 201);
    }
    if (method === "PUT" && path === "/default") {
      templates.forEach((item) => { item.is_default = item.id === body?.template_id; });
      return new Response(null, { status: 204 });
    }
    if (method === "POST" && path === "/") {
      const created = template({
        id: `t${templates.length + 1}`,
        name: String(body?.name),
        instructions: String(body?.instructions),
        category_id: (body?.category_id as string | null) ?? null,
      });
      templates.push(created);
      return json(created, 201);
    }
    if (method === "PATCH") {
      const target = templates.find((item) => `/${item.id}` === path)!;
      if (body && "name" in body) target.name = String(body.name);
      if (body && "instructions" in body) { target.instructions = String(body.instructions); target.version += 1; }
      if (body && "category_id" in body) target.category_id = body.category_id as string | null;
      return json(target);
    }
    return json({ detail: "unexpected" }, 404);
  });
  return { handler, calls, failing, templates };
}

const initial = () => ({
  categories: [{ id: "c1", name: "Sales" }, { id: "c2", name: "Support" }],
  templates: [
    template({ id: "t1", name: "Key results", category_id: "c1", is_default: true, provenance: "Owner proposal note." }),
    template({ id: "t2", name: "Follow-up", category_id: "c1", instructions: "Follow-up instructions" }),
    template({ id: "t3", name: "Free notes", category_id: null }),
  ],
});

let backend: ReturnType<typeof fakeBackend>;

async function renderReady(data = initial()) {
  backend = fakeBackend(data);
  vi.stubGlobal("fetch", backend.handler);
  render(<SummarySettings />);
  await screen.findByRole("heading", { name: "Sales" });
}

const row = (name: string) => screen.getByText(name, { selector: ".settings-template-name" }).closest("li")!;
const templatesSection = () => screen.getByRole("region", { name: t("settings:summaries.templatesTitle") });
const writes = () => backend.calls.filter((call) => call.method !== "GET");

beforeEach(() => {
  vi.stubGlobal("localStorage", {
    getItem: (key: string) => (key === "sauri_token" ? "synthetic-token" : null),
    setItem: vi.fn(),
    removeItem: vi.fn(),
  });
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("summary templates list", () => {
  it("explains the default template and that edits only affect future summaries", async () => {
    await renderReady();
    expect(screen.getByText(t("settings:summaries.help"))).toBeInTheDocument();
    expect(t("settings:summaries.help")).toMatch(/por defecto/);
    expect(t("settings:summaries.help")).toMatch(/futuros/);
  });

  it("groups templates by category, then without category, and marks the default", async () => {
    await renderReady();
    const headings = within(templatesSection()).getAllByRole("heading", { level: 3 }).map((heading) => heading.textContent);
    expect(headings).toEqual([t("settings:summaries.templatesTitle"), "Sales", "Support", t("settings:summaries.uncategorized")]);

    const commercial = screen.getByRole("region", { name: "Sales" });
    expect(within(commercial).getAllByRole("listitem").map((item) => item.querySelector(".settings-template-name")?.textContent))
      .toEqual(["Key results", "Follow-up"]);
    expect(within(commercial).queryByText(t("settings:summaries.emptyCategory"))).toBeNull();
    expect(within(screen.getByRole("region", { name: "Support" })).getByText(t("settings:summaries.emptyCategory"))).toBeInTheDocument();
    expect(within(screen.getByRole("region", { name: t("settings:summaries.uncategorized") })).getByText("Free notes")).toBeInTheDocument();

    expect(within(row("Key results")).getByText(t("settings:summaries.defaultBadge"))).toBeInTheDocument();
    expect(within(row("Follow-up")).queryByText(t("settings:summaries.defaultBadge"))).toBeNull();
    expect(screen.getAllByText(t("settings:summaries.defaultBadge"))).toHaveLength(1);
  });

  it("shows the provenance note as muted text", async () => {
    await renderReady();
    expect(within(row("Key results")).getByText("Owner proposal note.")).toBeInTheDocument();
    expect(within(row("Follow-up")).queryByText("Owner proposal note.")).toBeNull();
  });

  it("offers 'use as default' only on templates that are not the default, with accessible names", async () => {
    await renderReady();
    expect(screen.queryByRole("button", { name: t("settings:summaries.useAsDefaultLabel", { name: "Key results" }) })).toBeNull();
    expect(screen.getByRole("button", { name: t("settings:summaries.useAsDefaultLabel", { name: "Follow-up" }) })).toHaveTextContent(t("settings:summaries.useAsDefault"));
    expect(screen.getByRole("button", { name: t("settings:summaries.editLabel", { name: "Key results" }) })).toHaveTextContent(t("settings:summaries.edit"));
  });

  it("shows an empty state, and a load error that can be retried", async () => {
    backend = fakeBackend({ templates: [], categories: [] });
    vi.stubGlobal("fetch", backend.handler);
    backend.failing.add("GET /");
    render(<SummarySettings />);
    expect(await within(templatesSection()).findByRole("alert")).toHaveTextContent(t("settings:summaries.loadError"));
    expect(screen.getByRole("button", { name: t("settings:summaries.newTemplate") })).toBeDisabled();

    backend.failing.clear();
    fireEvent.click(screen.getByRole("button", { name: t("settings:summaries.retry") }));
    expect(await screen.findByText(t("settings:summaries.empty"))).toBeInTheDocument();
    expect(screen.getByRole("button", { name: t("settings:summaries.newTemplate") })).toBeEnabled();
  });

  it("sends the stored token and never lists with a body", async () => {
    await renderReady();
    const first = backend.handler.mock.calls[0];
    expect((first[1]?.headers as Record<string, string>).Authorization).toBe("Bearer synthetic-token");
    expect(backend.calls.slice(0, 2).map((call) => `${call.method} ${call.path}`).sort())
      .toEqual(["GET /", "GET /categories"]);
  });
});

describe("choosing the default template", () => {
  it("moves the mark at once and confirms, calling PUT /default with the template id", async () => {
    await renderReady();
    fireEvent.click(screen.getByRole("button", { name: t("settings:summaries.useAsDefaultLabel", { name: "Follow-up" }) }));
    expect(within(row("Follow-up")).getByText(t("settings:summaries.defaultBadge"))).toBeInTheDocument();
    expect(within(row("Key results")).queryByText(t("settings:summaries.defaultBadge"))).toBeNull();
    await waitFor(() => expect(within(templatesSection()).getByRole("status")).toHaveTextContent(t("settings:summaries.defaultSaved", { name: "Follow-up" })));
    expect(writes()).toEqual([{ method: "PUT", path: "/default", body: { template_id: "t2" } }]);
  });

  it("rolls back and says so when the API refuses", async () => {
    await renderReady();
    backend.failing.add("PUT /default");
    fireEvent.click(screen.getByRole("button", { name: t("settings:summaries.useAsDefaultLabel", { name: "Follow-up" }) }));
    expect(await within(templatesSection()).findByRole("alert")).toHaveTextContent(t("settings:summaries.defaultError"));
    expect(within(row("Key results")).getByText(t("settings:summaries.defaultBadge"))).toBeInTheDocument();
    expect(within(row("Follow-up")).queryByText(t("settings:summaries.defaultBadge"))).toBeNull();
    expect(screen.getAllByText(t("settings:summaries.defaultBadge"))).toHaveLength(1);
  });
});

describe("editing a template", () => {
  async function openEditor(name: string) {
    fireEvent.click(screen.getByRole("button", { name: t("settings:summaries.editLabel", { name }) }));
    return screen.findByRole("dialog", { name: t("settings:templateDialog.editTitle") });
  }

  it("fills the form, sends only the changed fields and updates the list", async () => {
    await renderReady();
    const dialog = await openEditor("Follow-up");
    expect(within(dialog).getByLabelText(t("settings:templateDialog.name"))).toHaveValue("Follow-up");
    expect(within(dialog).getByLabelText(t("settings:templateDialog.category"))).toHaveValue("c1");
    expect(within(dialog).getByLabelText(t("settings:templateDialog.instructions"))).toHaveValue("Follow-up instructions");

    fireEvent.change(within(dialog).getByLabelText(t("settings:templateDialog.name")), { target: { value: "Weekly follow-up" } });
    fireEvent.change(within(dialog).getByLabelText(t("settings:templateDialog.category")), { target: { value: "" } });
    fireEvent.click(within(dialog).getByRole("button", { name: t("settings:templateDialog.save") }));

    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(writes()).toEqual([{ method: "PATCH", path: "/t2", body: { name: "Weekly follow-up", category_id: null } }]);
    const uncategorized = screen.getByRole("region", { name: t("settings:summaries.uncategorized") });
    expect(within(uncategorized).getByText("Weekly follow-up")).toBeInTheDocument();
    expect(within(templatesSection()).getByRole("status")).toHaveTextContent(t("settings:summaries.templateSaved", { name: "Weekly follow-up" }));
  });

  it("sends the new instructions when they change", async () => {
    await renderReady();
    const dialog = await openEditor("Free notes");
    fireEvent.change(within(dialog).getByLabelText(t("settings:templateDialog.instructions")), { target: { value: "New text" } });
    fireEvent.click(within(dialog).getByRole("button", { name: t("settings:templateDialog.save") }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(writes()[0].body).toEqual({ instructions: "New text" });
  });

  it("closes without calling the API when nothing changed", async () => {
    await renderReady();
    const dialog = await openEditor("Follow-up");
    fireEvent.click(within(dialog).getByRole("button", { name: t("settings:templateDialog.save") }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(writes()).toEqual([]);
  });

  it("keeps the dialog and the list as they were when saving fails", async () => {
    await renderReady();
    backend.failing.add("PATCH /t2");
    const dialog = await openEditor("Follow-up");
    fireEvent.change(within(dialog).getByLabelText(t("settings:templateDialog.name")), { target: { value: "Changed" } });
    fireEvent.click(within(dialog).getByRole("button", { name: t("settings:templateDialog.save") }));
    expect(await within(dialog).findByRole("alert")).toHaveTextContent(t("settings:templateDialog.error"));
    expect(screen.getByRole("dialog", { name: t("settings:templateDialog.editTitle") })).toBeInTheDocument();
    expect(within(dialog).getByRole("button", { name: t("settings:templateDialog.save") })).toBeEnabled();
    fireEvent.click(within(dialog).getByRole("button", { name: t("settings:templateDialog.cancel") }));
    expect(screen.queryByText("Changed", { selector: ".settings-template-name" })).toBeNull();
    expect(screen.getByText("Follow-up", { selector: ".settings-template-name" })).toBeInTheDocument();
  });

  it("validates the name and instructions against the schema limits before calling the API", async () => {
    await renderReady();
    const dialog = await openEditor("Follow-up");
    const name = within(dialog).getByLabelText(t("settings:templateDialog.name"));
    const instructions = within(dialog).getByLabelText(t("settings:templateDialog.instructions"));

    fireEvent.change(name, { target: { value: "   " } });
    fireEvent.change(instructions, { target: { value: "" } });
    fireEvent.click(within(dialog).getByRole("button", { name: t("settings:templateDialog.save") }));
    expect(name).toHaveAttribute("aria-invalid", "true");
    expect(name).toHaveAccessibleDescription(t("settings:templateDialog.nameRequired"));
    expect(instructions).toHaveAttribute("aria-invalid", "true");
    expect(instructions).toHaveAccessibleDescription(new RegExp(t("settings:templateDialog.instructionsRequired")));

    fireEvent.change(name, { target: { value: "x".repeat(129) } });
    fireEvent.change(instructions, { target: { value: "ok" } });
    fireEvent.click(within(dialog).getByRole("button", { name: t("settings:templateDialog.save") }));
    expect(name).toHaveAccessibleDescription(t("settings:templateDialog.nameTooLong"));

    fireEvent.change(name, { target: { value: "x".repeat(128) } });
    fireEvent.click(within(dialog).getByRole("button", { name: t("settings:templateDialog.save") }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(writes()).toHaveLength(1);
  });

  it("closes with Escape without saving", async () => {
    await renderReady();
    await openEditor("Follow-up");
    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(writes()).toEqual([]);
  });
});

describe("creating templates and categories", () => {
  it("creates a template in a category and shows it in that group", async () => {
    await renderReady();
    fireEvent.click(screen.getByRole("button", { name: t("settings:summaries.newTemplate") }));
    const dialog = await screen.findByRole("dialog", { name: t("settings:templateDialog.createTitle") });
    fireEvent.change(within(dialog).getByLabelText(t("settings:templateDialog.name")), { target: { value: "  Support meeting " } });
    fireEvent.change(within(dialog).getByLabelText(t("settings:templateDialog.category")), { target: { value: "c2" } });
    fireEvent.change(within(dialog).getByLabelText(t("settings:templateDialog.instructions")), { target: { value: "Summarize the ticket" } });
    fireEvent.click(within(dialog).getByRole("button", { name: t("settings:templateDialog.create") }));

    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(writes()).toEqual([{
      method: "POST", path: "/",
      body: { name: "Support meeting", instructions: "Summarize the ticket", category_id: "c2" },
    }]);
    expect(within(screen.getByRole("region", { name: "Support" })).getByText("Support meeting")).toBeInTheDocument();
    expect(within(screen.getByRole("region", { name: "Support" })).queryByText(t("settings:summaries.emptyCategory"))).toBeNull();
  });

  it("does not add anything when creating fails", async () => {
    await renderReady();
    backend.failing.add("POST /");
    fireEvent.click(screen.getByRole("button", { name: t("settings:summaries.newTemplate") }));
    const dialog = await screen.findByRole("dialog", { name: t("settings:templateDialog.createTitle") });
    fireEvent.change(within(dialog).getByLabelText(t("settings:templateDialog.name")), { target: { value: "Draft" } });
    fireEvent.change(within(dialog).getByLabelText(t("settings:templateDialog.instructions")), { target: { value: "Text" } });
    fireEvent.click(within(dialog).getByRole("button", { name: t("settings:templateDialog.create") }));
    expect(await within(dialog).findByRole("alert")).toHaveTextContent(t("settings:templateDialog.error"));
    fireEvent.click(within(dialog).getByRole("button", { name: t("settings:templateDialog.cancel") }));
    expect(screen.queryByText("Draft", { selector: ".settings-template-name" })).toBeNull();
  });

  it("creates a category, which then appears as an empty group and in the template form", async () => {
    await renderReady();
    fireEvent.click(screen.getByRole("button", { name: t("settings:summaries.newCategory") }));
    const dialog = await screen.findByRole("dialog", { name: t("settings:categoryDialog.title") });
    fireEvent.change(within(dialog).getByLabelText(t("settings:categoryDialog.name")), { target: { value: "Management" } });
    fireEvent.click(within(dialog).getByRole("button", { name: t("settings:categoryDialog.create") }));

    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(writes()).toEqual([{ method: "POST", path: "/categories", body: { name: "Management" } }]);
    const group = screen.getByRole("region", { name: "Management" });
    expect(within(group).getByText(t("settings:summaries.emptyCategory"))).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: t("settings:summaries.newTemplate") }));
    const select = within(await screen.findByRole("dialog")).getByLabelText(t("settings:templateDialog.category"));
    expect(within(select).getByRole("option", { name: "Management" })).toBeInTheDocument();
  });

  it("validates the category name and reports a failed creation", async () => {
    await renderReady();
    fireEvent.click(screen.getByRole("button", { name: t("settings:summaries.newCategory") }));
    const dialog = await screen.findByRole("dialog");
    const name = within(dialog).getByLabelText(t("settings:categoryDialog.name"));
    fireEvent.click(within(dialog).getByRole("button", { name: t("settings:categoryDialog.create") }));
    expect(name).toHaveAccessibleDescription(t("settings:categoryDialog.nameRequired"));
    expect(writes()).toEqual([]);

    backend.failing.add("POST /categories");
    fireEvent.change(name, { target: { value: "Management" } });
    fireEvent.click(within(dialog).getByRole("button", { name: t("settings:categoryDialog.create") }));
    expect(await within(dialog).findByRole("alert")).toHaveTextContent(t("settings:categoryDialog.error"));
  });
});
