// «About Sauri» window: lays out the view the main process sends (every text already translated). Only text nodes
// are written, never HTML. The isotype on the left is static markup in index.html.
import type { AboutApi, AboutTone, AboutView } from "../shared/about-api.ts";

declare global {
  interface Window {
    sauriAbout: AboutApi;
  }
}

/** How often «Active for» is refreshed. */
const REFRESH_MS = 20_000;

const api = window.sauriAbout;
const byId = (id: string) => document.getElementById(id) as HTMLElement;

function el(tag: string, className: string, text?: string): HTMLElement {
  const element = document.createElement(tag);
  element.className = className;
  if (text !== undefined) element.textContent = text;
  return element;
}

function dot(tone: AboutTone): HTMLElement {
  const element = el("span", `dot dot--${tone}`);
  element.setAttribute("aria-hidden", "true");
  return element;
}

/** «label ........ value» */
function line(label: string, ...value: Node[]): HTMLElement {
  const row = el("div", "line");
  const term = el("dt", "line-label", label);
  const leader = el("span", "leader");
  leader.setAttribute("aria-hidden", "true");
  const detail = el("dd", "line-value");
  detail.append(...value);
  row.append(term, leader, detail);
  return row;
}

function state(text: string, tone: AboutTone): HTMLElement {
  const wrap = el("span", "state");
  wrap.append(dot(tone), el("span", `state-text state-text--${tone}`, text));
  return wrap;
}

function render(view: AboutView): void {
  document.documentElement.lang = view.lang;
  document.title = view.title;
  byId("badge").textContent = view.badge;
  byId("tagline").textContent = view.tagline;

  const lines = byId("lines");
  const sep = el("span", "sep", "·");
  sep.setAttribute("aria-hidden", "true");
  const web = line(view.web.label, el("span", "mono", view.web.value), sep, state(view.web.state, view.web.tone));

  const services = el("div", "group");
  services.append(el("dt", "group-label", view.services.label));
  const list = el("dd", "group-list");
  if (view.services.items.length === 0) list.append(el("p", "empty", view.services.empty));
  for (const item of view.services.items) {
    const row = el("div", "line line--service");
    const name = el("span", "line-label");
    name.append(dot(item.tone), document.createTextNode(item.name));
    const leader = el("span", "leader");
    leader.setAttribute("aria-hidden", "true");
    row.append(name, leader, el("span", `line-value state-text state-text--${item.tone}`, item.state));
    list.append(row);
  }
  services.append(list);

  const details = view.details.map((item) => line(item.label, document.createTextNode(item.value)));
  lines.replaceChildren(web, services, ...details);

  byId("credits").textContent = view.credits;
  const repo = byId("repo") as HTMLAnchorElement;
  repo.href = view.repository.url;
  repo.textContent = view.repository.text;
  repo.setAttribute("aria-label", view.repository.label);
  repo.title = view.repository.label;
  byId("copyright").textContent = view.copyright;
  document.body.dataset.ready = "true";
}

const refresh = () => void api.view().then(render);
api.onChange(render);
refresh();
setInterval(refresh, REFRESH_MS);
