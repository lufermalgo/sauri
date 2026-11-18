// Setup window: hardware check, name and folders (phase A), then the startup progress and any startup error.
import { formatGigabytes, type Locale, type MessageKey, t } from "../i18n.ts";
import type { HardwareReport } from "../main/hardware.ts";
import { FOLDER_KINDS, type UserFolders } from "../shared/folders.ts";
import type { FolderInfo, SetupApi, SetupState, View } from "../shared/setup-api.ts";

declare global {
  interface Window {
    sauriSetup: SetupApi;
  }
}

const api = window.sauriSetup;
const root = document.getElementById("app") as HTMLElement;

type Screen = "hardware" | "identity" | "folders" | "view";
let state: SetupState;
let screen: Screen = "hardware";
let hardware: HardwareReport | undefined;
let folders: FolderInfo[] = [];
let current: View | undefined;
let nameError = "";
let finishError = "";
let busy = false;

type Child = Node | string | null | undefined | false;

function h(tag: string, attrs: Record<string, string | boolean | ((event: Event) => void)> = {}, ...children: Child[]) {
  const element = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (typeof value === "function") element.addEventListener(key.slice(2), value);
    else if (value === true) element.setAttribute(key, "");
    else if (value !== false) element.setAttribute(key, value);
  }
  for (const child of children) if (child) element.append(child);
  return element;
}

const L = (key: MessageKey, vars?: Record<string, string | number>) => t(state.locale, key, vars);
const gb = (bytes: number) => formatGigabytes(state.locale, bytes);

function header(step?: number): HTMLElement {
  const select = h(
    "select",
    {
      id: "locale",
      onchange: (event) => void changeLocale((event.target as HTMLSelectElement).value as Locale),
    },
    h("option", { value: "es", selected: state.locale === "es" }, "Español"),
    h("option", { value: "en", selected: state.locale === "en" }, "English"),
  );
  return h(
    "header",
    {},
    h("span", { class: "brand" }, L("app.name")),
    step ? h("span", { class: "step" }, L("setup.step", { n: step })) : null,
    h("label", { for: "locale" }, L("setup.language"), select),
  );
}

async function changeLocale(locale: Locale): Promise<void> {
  await api.setLocale(locale);
  state.locale = locale;
  document.documentElement.lang = locale;
  render();
}

function hardwareScreen(): HTMLElement[] {
  const report = hardware as HardwareReport;
  const arch = report.problems.find((problem) => problem.code === "arch");
  const macos = report.problems.find((problem) => problem.code === "macos");
  const memory = report.warnings.find((warning) => warning.code.startsWith("memory"));
  const disk = report.warnings.find((warning) => warning.code === "disk_low");
  const row = (label: string, value: string, mark: "ok" | "warn" | "fail") =>
    h("div", { class: "row" }, h("span", { class: "label" }, label), h("span", {}, value), h("span", { class: `mark ${mark}` }, mark === "ok" ? "✓" : "!"));
  const notices: HTMLElement[] = [];
  if (arch) notices.push(h("p", { class: "notice fail" }, L("hardware.arch.fail")));
  if (macos && macos.code === "macos") {
    notices.push(h("p", { class: "notice fail" }, L("hardware.macos.fail", { version: macos.version, minimum: macos.minimum })));
  }
  if (memory?.code === "memory_lighter") {
    notices.push(h("p", { class: "notice warn" }, L("hardware.memory.lighter", { gib: memory.gib, needed: memory.needed, missing: memory.missing })));
  } else if (memory?.code === "memory_none") {
    const process = L(memory.process === "summary" ? "process.summary" : "process.transcription");
    notices.push(h("p", { class: "notice warn" }, L("hardware.memory.none", { gib: memory.gib, needed: memory.needed, process })));
  }
  if (disk?.code === "disk_low") {
    notices.push(h("p", { class: "notice warn" }, L("hardware.disk.low", { needed: gb(disk.neededBytes), missing: gb(disk.missingBytes) })));
  }
  const blocked = report.problems.length > 0;
  return [
    h("h1", {}, L("hardware.title")),
    h("p", { class: "intro" }, L("hardware.intro")),
    h(
      "div",
      { class: "rows" },
      row(L("hardware.arch"), arch ? report.arch : L("hardware.arch.ok"), arch ? "fail" : "ok"),
      row(L("hardware.macos"), report.macosVersion, macos ? "fail" : "ok"),
      row(L("hardware.memory"), `${report.memoryGib} GB`, memory ? "warn" : "ok"),
      row(L("hardware.disk"), gb(report.diskFreeBytes), disk ? "warn" : "ok"),
    ),
    ...notices,
    blocked ? h("p", { class: "notice fail" }, L("hardware.blocked")) : null,
    h(
      "div",
      { class: "actions" },
      blocked
        ? h("button", { class: "secondary", onclick: () => void api.quit() }, L("action.quit"))
        : h("button", { class: "primary", id: "hardware-continue", onclick: () => go(state.step) }, L("setup.continue")),
    ),
  ].filter(Boolean) as HTMLElement[];
}

function identityScreen(): HTMLElement[] {
  const input = h("input", {
    type: "text",
    id: "name",
    autocomplete: "name",
    maxlength: "255",
    value: state.name,
  }) as HTMLInputElement;
  const submit = async () => {
    if (busy) return;
    busy = true;
    const result = await api.saveName(input.value);
    busy = false;
    if (!result.ok) {
      nameError = L(result.error === "long" ? "identity.long" : "identity.empty");
      return render();
    }
    state.name = input.value.trim();
    nameError = "";
    go("folders");
  };
  input.addEventListener("keydown", (event) => {
    if ((event as KeyboardEvent).key === "Enter") void submit();
  });
  queueMicrotask(() => input.focus());
  return [
    h("h1", {}, L("identity.title")),
    h("p", { class: "intro" }, L("identity.intro")),
    h("div", { class: "field" }, h("label", { for: "name" }, L("identity.label")), input, h("p", { class: "error-text", role: "alert" }, nameError)),
    h(
      "div",
      { class: "actions" },
      h("button", { class: "secondary", onclick: () => go("hardware") }, L("setup.back")),
      h("button", { class: "primary", id: "identity-continue", onclick: () => void submit() }, L("setup.continue")),
    ),
  ];
}

function issueText(info: FolderInfo): string {
  return info.issue ? L(`folders.error.${info.issue}` as MessageKey) : "";
}

function foldersScreen(): HTMLElement[] {
  const cards = folders.map((info) =>
    h(
      "div",
      { class: info.issue ? "folder invalid" : "folder", "data-kind": info.kind },
      h(
        "div",
        { class: "folder-head" },
        h("strong", {}, L(`folder.${info.kind}` as MessageKey)),
        h("button", { class: "secondary", onclick: () => void choose(info.kind) }, L("folders.change")),
      ),
      h("p", { class: "hint" }, L(`folders.hint.${info.kind}` as MessageKey)),
      h("div", { class: "path" }, info.path),
      info.freeBytes !== null ? h("div", { class: "free" }, L("folders.free", { free: gb(info.freeBytes) })) : null,
      info.issue ? h("p", { class: "error-text", role: "alert" }, issueText(info)) : null,
    ),
  );
  const invalid = folders.some((info) => info.issue);
  return [
    h("h1", {}, L("folders.title")),
    h("p", { class: "intro" }, L("folders.intro")),
    ...cards,
    finishError ? h("p", { class: "notice fail", role: "alert" }, finishError) : null,
    h(
      "div",
      { class: "actions" },
      h("button", { class: "secondary", onclick: () => void back() }, L("setup.back")),
      h("button", { class: "primary", id: "folders-continue", disabled: invalid || busy, onclick: () => void finish() }, L("folders.continue")),
    ),
  ].filter(Boolean) as HTMLElement[];
}

function currentFolders(): UserFolders {
  return Object.fromEntries(folders.map((info) => [info.kind, info.path])) as UserFolders;
}

async function choose(kind: FolderInfo["kind"]): Promise<void> {
  const picked = await api.choose(kind);
  if (!picked) return;
  folders = await api.inspect({ ...currentFolders(), [kind]: picked });
  render();
}

async function back(): Promise<void> {
  await api.back();
  go("identity");
}

async function finish(): Promise<void> {
  if (busy) return;
  busy = true;
  finishError = "";
  render();
  const result = await api.finish(currentFolders());
  busy = false;
  if (result.ok) return;
  if (result.folders) folders = result.folders;
  if (result.message) finishError = result.message;
  screen = "folders";
  render();
}

function viewScreen(view: View): HTMLElement[] {
  if (view.view === "progress") {
    return [h("div", { class: "progress" }, h("div", { class: "spinner", "aria-hidden": "true" }), h("p", { id: "progress" }, L(view.key)))];
  }
  return [
    h("h1", {}, L("error.title")),
    h("p", { class: "notice fail", role: "alert", id: "startup-error" }, view.message),
    h(
      "div",
      { class: "actions" },
      h("button", { class: "secondary", onclick: () => void api.openLogs() }, L("action.logs")),
      h("button", { class: "secondary", onclick: () => void api.quit() }, L("action.quit")),
      view.canRetry ? h("button", { class: "primary", onclick: () => void api.retry() }, L("action.retry")) : null,
    ),
  ];
}

function go(next: Screen): void {
  screen = next;
  if (next === "folders") void loadFolders();
  render();
}

async function loadFolders(): Promise<void> {
  folders = await api.inspect(state.folders);
  render();
}

function render(): void {
  const step = { hardware: 1, identity: 2, folders: 3, view: 0 }[screen];
  let body: HTMLElement[] = [];
  if (screen === "view" && current) body = viewScreen(current);
  else if (screen === "hardware" && hardware) body = hardwareScreen();
  else if (screen === "identity") body = identityScreen();
  else if (screen === "folders" && folders.length === FOLDER_KINDS.length) body = foldersScreen();
  root.replaceChildren(header(state.mode === "setup" && step ? step : undefined), h("section", {}, ...body));
}

api.onView((view) => {
  current = view;
  screen = "view";
  render();
});

async function start(): Promise<void> {
  state = await api.state();
  document.documentElement.lang = state.locale;
  if (state.mode === "startup" || state.view) {
    current = state.view ?? { view: "progress", key: "startup.title" };
    screen = "view";
    return render();
  }
  hardware = await api.hardware();
  // A resumed setup opens at the pending step, unless this Mac cannot run Sauri.
  screen = hardware.problems.length === 0 && state.step === "folders" ? "folders" : "hardware";
  if (screen === "folders") return go("folders");
  render();
}

void start();
