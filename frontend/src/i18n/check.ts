import ts from "typescript";

/**
 * Checks behind `npm run i18n:check` (and the test that runs it with `npm test`):
 *  - every language has the same keys as Spanish, the source of truth, with the same variables;
 *  - plural keys carry the forms each language needs;
 *  - no component or helper holds user-facing Spanish text (it lives in `src/locales/`).
 */

export type Resource = { [key: string]: string | Resource };

const PLURAL_SUFFIX = /_(zero|one|two|few|many|other)$/;

/** Dot-separated keys of every string in a namespace file. */
export function flatten(resource: Resource, prefix = ""): Map<string, string> {
  const out = new Map<string, string>();
  for (const [key, value] of Object.entries(resource)) {
    const path = prefix ? `${prefix}.${key}` : key;
    if (typeof value === "string") out.set(path, value);
    else for (const [inner, text] of flatten(value, path)) out.set(inner, text);
  }
  return out;
}

/** Variable names used by a translation: `{{name}}`, `{{name, format}}`. */
export function variablesOf(text: string): string[] {
  return [...new Set([...text.matchAll(/\{\{\s*([\w.]+)\s*(?:,[^}]*)?\}\}/g)].map((match) => match[1]))].sort();
}

interface Entry { variables: string[]; forms: Set<string> }

/** Keys with their plural forms folded together: "speakers_one" and "speakers_other" are one entry. */
function entries(resource: Resource): Map<string, Entry> {
  const out = new Map<string, Entry>();
  for (const [path, text] of flatten(resource)) {
    const form = PLURAL_SUFFIX.exec(path)?.[1] ?? "";
    const base = path.replace(PLURAL_SUFFIX, "");
    const entry = out.get(base) ?? { variables: [], forms: new Set<string>() };
    entry.variables = [...new Set([...entry.variables, ...variablesOf(text)])].sort();
    if (form) entry.forms.add(form);
    out.set(base, entry);
  }
  return out;
}

/** The plural forms a language must provide (`many` only matters for very large round numbers in Spanish). */
export function requiredPluralForms(language: string): string[] {
  const categories = new Intl.PluralRules(language).resolvedOptions().pluralCategories;
  return categories.filter((category) => category !== "many").sort();
}

/**
 * Problems found when `target` (one namespace of a language) is compared with `source` (Spanish).
 * Each message names the namespace and key so it can be fixed directly.
 */
export function compareNamespace(namespace: string, source: Resource, target: Resource, language: string): string[] {
  const problems: string[] = [];
  const from = entries(source);
  const to = entries(target);
  for (const [key, entry] of from) {
    const other = to.get(key);
    if (!other) { problems.push(`${language}/${namespace}: missing key "${key}"`); continue; }
    if (entry.variables.join() !== other.variables.join()) {
      problems.push(`${language}/${namespace}: "${key}" uses variables [${other.variables}] but Spanish uses [${entry.variables}]`);
    }
  }
  for (const key of to.keys()) if (!from.has(key)) problems.push(`${language}/${namespace}: extra key "${key}" not in Spanish`);
  for (const [key, entry] of to) {
    if (entry.forms.size === 0) continue;
    for (const form of requiredPluralForms(language)) {
      if (!entry.forms.has(form)) problems.push(`${language}/${namespace}: plural "${key}" lacks the "_${form}" form`);
    }
  }
  for (const [path, text] of flatten(target)) {
    if (text.trim() === "") problems.push(`${language}/${namespace}: "${path}" is empty`);
  }
  return problems;
}

/** Spanish plural forms must also be complete in the source language itself. */
export function checkSourcePlurals(namespace: string, source: Resource): string[] {
  const problems: string[] = [];
  for (const [key, entry] of entries(source)) {
    if (entry.forms.size === 0) continue;
    for (const form of requiredPluralForms("es")) {
      if (!entry.forms.has(form)) problems.push(`es/${namespace}: plural "${key}" lacks the "_${form}" form`);
    }
  }
  return problems;
}

// --- hard-coded Spanish in source files ---

const SPANISH_CHARACTERS = /[áéíóúñüÁÉÍÓÚÑÜ¿¡]/;
// Words that are Spanish and nothing else, to catch accent-free strings ("Guardar", "Reintentar").
const SPANISH_WORDS = new Set([
  "para", "con", "sin", "los", "las", "una", "del", "que", "por", "cuando", "hay", "puede", "todavía",
  "guardar", "cancelar", "eliminar", "cargando", "cerrar", "descargar", "buscar", "subir", "iniciar", "reintentar",
  "grabacion", "grabaciones", "reunion", "reuniones", "hablante", "hablantes", "resumen", "transcripcion",
  "biblioteca", "configuracion", "contrasena", "correo", "titulo", "archivo", "borrador", "nombre", "ocultar", "mostrar",
]);

export interface Finding { line: number; text: string }

export const IGNORE_MARKER = "i18n-ignore";

function looksSpanish(text: string): boolean {
  if (SPANISH_CHARACTERS.test(text)) return true;
  return (text.match(/[A-Za-z]+/g) ?? []).some((word) => SPANISH_WORDS.has(word.toLowerCase()));
}

/** String literals and JSX text in `source` that read as Spanish. A line holding `i18n-ignore` is skipped. */
export function findHardcodedSpanish(source: string, fileName = "file.tsx"): Finding[] {
  const kind = fileName.endsWith("x") ? ts.ScriptKind.TSX : ts.ScriptKind.TS;
  const file = ts.createSourceFile(fileName, source, ts.ScriptTarget.Latest, true, kind);
  const lines = source.split("\n");
  const findings: Finding[] = [];
  const visit = (node: ts.Node) => {
    let text: string | null = null;
    if (ts.isStringLiteral(node) || ts.isNoSubstitutionTemplateLiteral(node)) text = node.text;
    else if (ts.isTemplateHead(node) || ts.isTemplateMiddle(node) || ts.isTemplateTail(node)) text = node.text;
    else if (ts.isJsxText(node)) text = node.text;
    // Import paths and type-only string literals are never shown to anyone.
    const hidden = node.parent && (ts.isImportDeclaration(node.parent) || ts.isExportDeclaration(node.parent)
      || ts.isLiteralTypeNode(node.parent) || ts.isImportTypeNode(node.parent));
    if (text !== null && !hidden && text.trim() !== "" && looksSpanish(text)) {
      const line = file.getLineAndCharacterOfPosition(node.getStart()).line;
      if (!lines[line]?.includes(IGNORE_MARKER)) findings.push({ line: line + 1, text: text.trim().slice(0, 60) });
    }
    ts.forEachChild(node, visit);
  };
  visit(file);
  return findings;
}

/** Files whose Spanish is expected: translations, tests and the checker itself. */
export function isExemptFromSpanishCheck(path: string): boolean {
  const normalized = path.replace(/\\/g, "/");
  return /\/(locales|copy|test|__tests__)\//.test(normalized)
    || /\.test\.tsx?$/.test(normalized)
    || normalized.endsWith("/i18n/check.ts")
    || normalized.endsWith(".d.ts");
}
