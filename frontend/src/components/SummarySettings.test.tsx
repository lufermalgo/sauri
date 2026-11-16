// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import "@testing-library/jest-dom/vitest";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { copy } from "../copy/es";
import { answerEnginesApi } from "./engineApiStub";
import { SummarySettings } from "./settings/SummarySettings";

const text = copy.settings.summaries;
const dialogText = copy.settings.templateDialog;

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
const templatesSection = () => screen.getByRole("region", { name: text.templatesTitle });
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
    expect(screen.getByText(text.help)).toBeInTheDocument();
    expect(text.help).toMatch(/por defecto/);
    expect(text.help).toMatch(/futuros/);
  });

  it("groups templates by category, then without category, and marks the default", async () => {
    await renderReady();
    const headings = within(templatesSection()).getAllByRole("heading", { level: 3 }).map((heading) => heading.textContent);
    expect(headings).toEqual([text.templatesTitle, "Sales", "Support", text.uncategorized]);

    const commercial = screen.getByRole("region", { name: "Sales" });
    expect(within(commercial).getAllByRole("listitem").map((item) => item.querySelector(".settings-template-name")?.textContent))
      .toEqual(["Key results", "Follow-up"]);
    expect(within(commercial).queryByText(text.emptyCategory)).toBeNull();
    expect(within(screen.getByRole("region", { name: "Support" })).getByText(text.emptyCategory)).toBeInTheDocument();
    expect(within(screen.getByRole("region", { name: text.uncategorized })).getByText("Free notes")).toBeInTheDocument();

    expect(within(row("Key results")).getByText(text.defaultBadge)).toBeInTheDocument();
    expect(within(row("Follow-up")).queryByText(text.defaultBadge)).toBeNull();
    expect(screen.getAllByText(text.defaultBadge)).toHaveLength(1);
  });

  it("shows the provenance note as muted text", async () => {
    await renderReady();
    expect(within(row("Key results")).getByText("Owner proposal note.")).toBeInTheDocument();
    expect(within(row("Follow-up")).queryByText("Owner proposal note.")).toBeNull();
  });

  it("offers 'use as default' only on templates that are not the default, with accessible names", async () => {
    await renderReady();
    expect(screen.queryByRole("button", { name: text.useAsDefaultLabel("Key results") })).toBeNull();
    expect(screen.getByRole("button", { name: text.useAsDefaultLabel("Follow-up") })).toHaveTextContent(text.useAsDefault);
    expect(screen.getByRole("button", { name: text.editLabel("Key results") })).toHaveTextContent(text.edit);
  });

  it("shows an empty state, and a load error that can be retried", async () => {
    backend = fakeBackend({ templates: [], categories: [] });
    vi.stubGlobal("fetch", backend.handler);
    backend.failing.add("GET /");
    render(<SummarySettings />);
    expect(await within(templatesSection()).findByRole("alert")).toHaveTextContent(text.loadError);
    expect(screen.getByRole("button", { name: text.newTemplate })).toBeDisabled();

    backend.failing.clear();
    fireEvent.click(screen.getByRole("button", { name: text.retry }));
    expect(await screen.findByText(text.empty)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: text.newTemplate })).toBeEnabled();
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
    fireEvent.click(screen.getByRole("button", { name: text.useAsDefaultLabel("Follow-up") }));
    expect(within(row("Follow-up")).getByText(text.defaultBadge)).toBeInTheDocument();
    expect(within(row("Key results")).queryByText(text.defaultBadge)).toBeNull();
    await waitFor(() => expect(within(templatesSection()).getByRole("status")).toHaveTextContent(text.defaultSaved("Follow-up")));
    expect(writes()).toEqual([{ method: "PUT", path: "/default", body: { template_id: "t2" } }]);
  });

  it("rolls back and says so when the API refuses", async () => {
    await renderReady();
    backend.failing.add("PUT /default");
    fireEvent.click(screen.getByRole("button", { name: text.useAsDefaultLabel("Follow-up") }));
    expect(await within(templatesSection()).findByRole("alert")).toHaveTextContent(text.defaultError);
    expect(within(row("Key results")).getByText(text.defaultBadge)).toBeInTheDocument();
    expect(within(row("Follow-up")).queryByText(text.defaultBadge)).toBeNull();
    expect(screen.getAllByText(text.defaultBadge)).toHaveLength(1);
  });
});

describe("editing a template", () => {
  async function openEditor(name: string) {
    fireEvent.click(screen.getByRole("button", { name: text.editLabel(name) }));
    return screen.findByRole("dialog", { name: dialogText.editTitle });
  }

  it("fills the form, sends only the changed fields and updates the list", async () => {
    await renderReady();
    const dialog = await openEditor("Follow-up");
    expect(within(dialog).getByLabelText(dialogText.name)).toHaveValue("Follow-up");
    expect(within(dialog).getByLabelText(dialogText.category)).toHaveValue("c1");
    expect(within(dialog).getByLabelText(dialogText.instructions)).toHaveValue("Follow-up instructions");

    fireEvent.change(within(dialog).getByLabelText(dialogText.name), { target: { value: "Weekly follow-up" } });
    fireEvent.change(within(dialog).getByLabelText(dialogText.category), { target: { value: "" } });
    fireEvent.click(within(dialog).getByRole("button", { name: dialogText.save }));

    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(writes()).toEqual([{ method: "PATCH", path: "/t2", body: { name: "Weekly follow-up", category_id: null } }]);
    const uncategorized = screen.getByRole("region", { name: text.uncategorized });
    expect(within(uncategorized).getByText("Weekly follow-up")).toBeInTheDocument();
    expect(within(templatesSection()).getByRole("status")).toHaveTextContent(text.templateSaved("Weekly follow-up"));
  });

  it("sends the new instructions when they change", async () => {
    await renderReady();
    const dialog = await openEditor("Free notes");
    fireEvent.change(within(dialog).getByLabelText(dialogText.instructions), { target: { value: "New text" } });
    fireEvent.click(within(dialog).getByRole("button", { name: dialogText.save }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(writes()[0].body).toEqual({ instructions: "New text" });
  });

  it("closes without calling the API when nothing changed", async () => {
    await renderReady();
    const dialog = await openEditor("Follow-up");
    fireEvent.click(within(dialog).getByRole("button", { name: dialogText.save }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(writes()).toEqual([]);
  });

  it("keeps the dialog and the list as they were when saving fails", async () => {
    await renderReady();
    backend.failing.add("PATCH /t2");
    const dialog = await openEditor("Follow-up");
    fireEvent.change(within(dialog).getByLabelText(dialogText.name), { target: { value: "Changed" } });
    fireEvent.click(within(dialog).getByRole("button", { name: dialogText.save }));
    expect(await within(dialog).findByRole("alert")).toHaveTextContent(dialogText.error);
    expect(screen.getByRole("dialog", { name: dialogText.editTitle })).toBeInTheDocument();
    expect(within(dialog).getByRole("button", { name: dialogText.save })).toBeEnabled();
    fireEvent.click(within(dialog).getByRole("button", { name: dialogText.cancel }));
    expect(screen.queryByText("Changed", { selector: ".settings-template-name" })).toBeNull();
    expect(screen.getByText("Follow-up", { selector: ".settings-template-name" })).toBeInTheDocument();
  });

  it("validates the name and instructions against the schema limits before calling the API", async () => {
    await renderReady();
    const dialog = await openEditor("Follow-up");
    const name = within(dialog).getByLabelText(dialogText.name);
    const instructions = within(dialog).getByLabelText(dialogText.instructions);

    fireEvent.change(name, { target: { value: "   " } });
    fireEvent.change(instructions, { target: { value: "" } });
    fireEvent.click(within(dialog).getByRole("button", { name: dialogText.save }));
    expect(name).toHaveAttribute("aria-invalid", "true");
    expect(name).toHaveAccessibleDescription(dialogText.nameRequired);
    expect(instructions).toHaveAttribute("aria-invalid", "true");
    expect(instructions).toHaveAccessibleDescription(new RegExp(dialogText.instructionsRequired));

    fireEvent.change(name, { target: { value: "x".repeat(129) } });
    fireEvent.change(instructions, { target: { value: "ok" } });
    fireEvent.click(within(dialog).getByRole("button", { name: dialogText.save }));
    expect(name).toHaveAccessibleDescription(dialogText.nameTooLong);

    fireEvent.change(name, { target: { value: "x".repeat(128) } });
    fireEvent.click(within(dialog).getByRole("button", { name: dialogText.save }));
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
    fireEvent.click(screen.getByRole("button", { name: text.newTemplate }));
    const dialog = await screen.findByRole("dialog", { name: dialogText.createTitle });
    fireEvent.change(within(dialog).getByLabelText(dialogText.name), { target: { value: "  Support meeting " } });
    fireEvent.change(within(dialog).getByLabelText(dialogText.category), { target: { value: "c2" } });
    fireEvent.change(within(dialog).getByLabelText(dialogText.instructions), { target: { value: "Summarize the ticket" } });
    fireEvent.click(within(dialog).getByRole("button", { name: dialogText.create }));

    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(writes()).toEqual([{
      method: "POST", path: "/",
      body: { name: "Support meeting", instructions: "Summarize the ticket", category_id: "c2" },
    }]);
    expect(within(screen.getByRole("region", { name: "Support" })).getByText("Support meeting")).toBeInTheDocument();
    expect(within(screen.getByRole("region", { name: "Support" })).queryByText(text.emptyCategory)).toBeNull();
  });

  it("does not add anything when creating fails", async () => {
    await renderReady();
    backend.failing.add("POST /");
    fireEvent.click(screen.getByRole("button", { name: text.newTemplate }));
    const dialog = await screen.findByRole("dialog", { name: dialogText.createTitle });
    fireEvent.change(within(dialog).getByLabelText(dialogText.name), { target: { value: "Draft" } });
    fireEvent.change(within(dialog).getByLabelText(dialogText.instructions), { target: { value: "Text" } });
    fireEvent.click(within(dialog).getByRole("button", { name: dialogText.create }));
    expect(await within(dialog).findByRole("alert")).toHaveTextContent(dialogText.error);
    fireEvent.click(within(dialog).getByRole("button", { name: dialogText.cancel }));
    expect(screen.queryByText("Draft", { selector: ".settings-template-name" })).toBeNull();
  });

  it("creates a category, which then appears as an empty group and in the template form", async () => {
    await renderReady();
    fireEvent.click(screen.getByRole("button", { name: text.newCategory }));
    const dialog = await screen.findByRole("dialog", { name: copy.settings.categoryDialog.title });
    fireEvent.change(within(dialog).getByLabelText(copy.settings.categoryDialog.name), { target: { value: "Management" } });
    fireEvent.click(within(dialog).getByRole("button", { name: copy.settings.categoryDialog.create }));

    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(writes()).toEqual([{ method: "POST", path: "/categories", body: { name: "Management" } }]);
    const group = screen.getByRole("region", { name: "Management" });
    expect(within(group).getByText(text.emptyCategory)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: text.newTemplate }));
    const select = within(await screen.findByRole("dialog")).getByLabelText(dialogText.category);
    expect(within(select).getByRole("option", { name: "Management" })).toBeInTheDocument();
  });

  it("validates the category name and reports a failed creation", async () => {
    await renderReady();
    fireEvent.click(screen.getByRole("button", { name: text.newCategory }));
    const dialog = await screen.findByRole("dialog");
    const name = within(dialog).getByLabelText(copy.settings.categoryDialog.name);
    fireEvent.click(within(dialog).getByRole("button", { name: copy.settings.categoryDialog.create }));
    expect(name).toHaveAccessibleDescription(copy.settings.categoryDialog.nameRequired);
    expect(writes()).toEqual([]);

    backend.failing.add("POST /categories");
    fireEvent.change(name, { target: { value: "Management" } });
    fireEvent.click(within(dialog).getByRole("button", { name: copy.settings.categoryDialog.create }));
    expect(await within(dialog).findByRole("alert")).toHaveTextContent(copy.settings.categoryDialog.error);
  });
});
