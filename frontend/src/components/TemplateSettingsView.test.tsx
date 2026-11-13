// @vitest-environment jsdom
/** T23/#291 RED — personal template settings, R3–R5, design §7/D12.
 * Synthetic data only. API mocks implement the approved client contract, not HTTP
 * mapping (T24). No seed, template grammar, deletion or no-default fallback.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import type { ComponentType } from "react";
import type { SummaryTemplate, TemplateCategory } from "@sauri/shared-types";

const api = vi.hoisted(() => ({
  listTemplates: vi.fn(), createTemplate: vi.fn(), updateTemplate: vi.fn(),
  listCategories: vi.fn(), createCategory: vi.fn(), setDefaultTemplate: vi.fn(),
}));
vi.mock("../api", () => api);

const ownerId = "synthetic-owner";
const timestamp = "2026-11-13T00:00:00Z";
const opaque = "  Prioritize agreements\n{opaque text}: <literal> & next steps  ";
const category: TemplateCategory = {
  id: "cat-project", ownerId, name: "Project", createdAt: timestamp,
};
function template(overrides: Partial<SummaryTemplate> = {}): SummaryTemplate {
  return {
    id: "tpl-one", ownerId, name: "Agreements", instructions: opaque,
    version: 1, isDefault: true, createdAt: timestamp, updatedAt: timestamp,
    ...overrides,
  };
}
const first = template();
const second = template({ id: "tpl-two", name: "Follow-up", isDefault: false, categoryId: category.id });

// Import inside the test lifecycle so missing production code is an observable
// RED assertion (all tests collect), without a production stub or TS suppression.
// T24 replaces this with a static import once the component exists.
async function openSettings() {
  const modulePath = new URL("./TemplateSettingsView.tsx", import.meta.url).pathname;
  const module: { TemplateSettingsView: ComponentType } = await import(/* @vite-ignore */ modulePath);
  render(<module.TemplateSettingsView />);
  await screen.findByText(first.name);
}

// Actions are scoped by their template name, not list layout/classes.
function rowFor(name: string): HTMLElement {
  const label = screen.getByText(name, { exact: true });
  let element = label.parentElement;
  while (element && element !== document.body) {
    if (within(element).queryByRole("button", { name: /edit/i })) return element;
    element = element.parentElement;
  }
  throw new Error(`No accessible template actions associated with ${name}`);
}
function fillTemplate(name: string, instructions: string) {
  fireEvent.change(screen.getByRole("textbox", { name: /template name/i }), { target: { value: name } });
  fireEvent.change(screen.getByRole("textbox", { name: /instructions/i }), { target: { value: instructions } });
}
function saveTemplate() {
  fireEvent.click(screen.getByRole("button", { name: /^(save template|create template)$/i }));
}

beforeEach(() => {
  vi.resetAllMocks();
  api.listTemplates.mockResolvedValue([first, second]);
  api.listCategories.mockResolvedValue([category]);
  api.setDefaultTemplate.mockResolvedValue(undefined); // API setter returns 204.
});
afterEach(cleanup);

describe("personal template settings (T23 RED)", () => {
  it("lists the caller's templates and marks only the configured default", async () => {
    await openSettings();
    expect(api.listTemplates).toHaveBeenCalled();
    expect(api.listCategories).toHaveBeenCalled();
    expect(screen.getByText(second.name)).toBeDefined();
    expect(within(rowFor(first.name)).getByText(/^(default)$/i)).toBeDefined();
    expect(within(rowFor(second.name)).queryByText(/^(default)$/i)).toBeNull();
  });

  it("creates multiple personal templates, preserving opaque instructions exactly", async () => {
    const third = template({ id: "tpl-three", name: "Third", isDefault: false });
    const fourth = template({ id: "tpl-four", name: "Fourth", isDefault: false });
    api.createTemplate.mockResolvedValueOnce(third).mockResolvedValueOnce(fourth);
    api.listTemplates.mockResolvedValueOnce([first, second])
      .mockResolvedValueOnce([first, second, third])
      .mockResolvedValue([first, second, third, fourth]);
    await openSettings();
    fillTemplate(third.name, opaque);
    saveTemplate();
    await waitFor(() => expect(api.createTemplate).toHaveBeenCalledTimes(1));
    await screen.findByText(third.name);
    fillTemplate(fourth.name, opaque + "\nAnother perspective");
    saveTemplate();
    await waitFor(() => expect(api.createTemplate).toHaveBeenCalledTimes(2));
    expect(api.createTemplate.mock.calls[0][0]).toMatchObject({ name: third.name, instructions: opaque });
    expect(api.createTemplate.mock.calls[1][0]).toMatchObject({ name: fourth.name, instructions: opaque + "\nAnother perspective" });
    // No category required: both omission and explicit null satisfy the contract.
    expect(api.createTemplate.mock.calls[0][0].categoryId ?? null).toBeNull();
    await screen.findByText(fourth.name);
  });

  it("loads an owned template for editing and saves its exact instruction string", async () => {
    const revised = "\n  Free text: [no schema] & <literal>  \n";
    api.updateTemplate.mockResolvedValue(template({ instructions: revised, version: 2 }));
    await openSettings();
    fireEvent.click(within(rowFor(first.name)).getByRole("button", { name: /edit/i }));
    const editor = screen.getByRole("textbox", { name: /instructions/i }) as HTMLTextAreaElement;
    expect(editor.value).toBe(opaque);
    fillTemplate(first.name, revised);
    saveTemplate();
    await waitFor(() => expect(api.updateTemplate).toHaveBeenCalledWith(first.id, expect.objectContaining({ instructions: revised })));
    expect(api.createTemplate).not.toHaveBeenCalled();
  });

  it("assigns an optional existing category and supports multiple templates in it", async () => {
    const created = template({ id: "tpl-three", name: "Same category", categoryId: category.id, isDefault: false });
    api.createTemplate.mockResolvedValue(created);
    await openSettings();
    fillTemplate(created.name, opaque);
    fireEvent.change(screen.getByRole("combobox", { name: /category/i }), { target: { value: category.id } });
    saveTemplate();
    await waitFor(() => expect(api.createTemplate).toHaveBeenCalledWith(expect.objectContaining({ name: created.name, categoryId: category.id })));
    expect(screen.getByText(second.name)).toBeDefined();
  });

  it("removes an edited category with explicit null, not an omitted PATCH field", async () => {
    api.updateTemplate.mockResolvedValue(template({ ...second, categoryId: undefined, version: 2 }));
    await openSettings();
    fireEvent.click(within(rowFor(second.name)).getByRole("button", { name: /edit/i }));
    const select = screen.getByRole("combobox", { name: /category/i }) as HTMLSelectElement;
    expect(select.value).toBe(category.id);
    fireEvent.change(select, { target: { value: "" } });
    saveTemplate();
    await waitFor(() => expect(api.updateTemplate).toHaveBeenCalledWith(second.id, expect.objectContaining({ categoryId: null })));
  });

  it("creates a category inline and makes it selectable", async () => {
    const created = { ...category, id: "cat-new", name: "New category" };
    api.createCategory.mockResolvedValue(created);
    api.listCategories.mockResolvedValueOnce([category]).mockResolvedValue([category, created]);
    await openSettings();
    fireEvent.change(screen.getByRole("textbox", { name: /category name/i }), { target: { value: created.name } });
    fireEvent.click(screen.getByRole("button", { name: /^(create category)$/i }));
    await waitFor(() => expect(api.createCategory).toHaveBeenCalledWith(created.name));
    const select = screen.getByRole("combobox", { name: /category/i });
    await waitFor(() => expect(within(select).getByRole("option", { name: created.name })).toBeDefined());
  });

  it("sets an owned template as the single personal default across categories", async () => {
    api.listTemplates.mockResolvedValueOnce([first, second]).mockResolvedValue([
      template({ isDefault: false }), { ...second, isDefault: true },
    ]);
    await openSettings();
    fireEvent.click(within(rowFor(second.name)).getByRole("button", { name: /set as default/i }));
    await waitFor(() => expect(api.setDefaultTemplate).toHaveBeenCalledWith(second.id));
    await waitFor(() => expect(within(rowFor(second.name)).getByText(/^(default)$/i)).toBeDefined());
    expect(within(rowFor(first.name)).queryByText(/^(default)$/i)).toBeNull();
    expect(api.updateTemplate).not.toHaveBeenCalled();
  });
});
