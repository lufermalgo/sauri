import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import {
  checkSourcePlurals, compareNamespace, findHardcodedSpanish, flatten, isExemptFromSpanishCheck, requiredPluralForms,
  variablesOf, type Resource,
} from "./check";

const localesDir = join(import.meta.dirname, "..", "locales");

function read(language: string): Record<string, Resource> {
  const dir = join(localesDir, language);
  return Object.fromEntries(readdirSync(dir).filter((file) => file.endsWith(".json"))
    .map((file) => [file.slice(0, -5), JSON.parse(readFileSync(join(dir, file), "utf8")) as Resource]));
}

function sources(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    return statSync(path).isDirectory() ? sources(path) : /\.tsx?$/.test(name) ? [path] : [];
  });
}

describe("the real translation files", () => {
  const es = read("es");
  const en = read("en");

  it("have English for every Spanish namespace and key, with the same variables", () => {
    expect(Object.keys(en).sort()).toEqual(Object.keys(es).sort());
    const problems = Object.keys(es).flatMap((namespace) => compareNamespace(namespace, es[namespace], en[namespace], "en"));
    expect(problems).toEqual([]);
  });

  it("carry complete plural forms in Spanish", () => {
    expect(Object.keys(es).flatMap((namespace) => checkSourcePlurals(namespace, es[namespace]))).toEqual([]);
  });

  it("leave no Spanish text in components or helpers", () => {
    const found = sources(join(import.meta.dirname, "..")).filter((file) => !isExemptFromSpanishCheck(file))
      .flatMap((file) => findHardcodedSpanish(readFileSync(file, "utf8"), file).map((finding) => `${file}:${finding.line} ${finding.text}`));
    expect(found).toEqual([]);
  });
});

describe("compareNamespace", () => {
  const source: Resource = { title: "Hola {{name}}", count_one: "{{count}} cosa", count_other: "{{count}} cosas", nested: { a: "A" } };

  it("accepts a faithful translation", () => {
    const target: Resource = { title: "Hello {{name}}", count_one: "{{count}} thing", count_other: "{{count}} things", nested: { a: "A" } };
    expect(compareNamespace("demo", source, target, "en")).toEqual([]);
  });

  it("reports a key missing in English and a key missing in Spanish", () => {
    const target: Resource = { title: "Hello {{name}}", count_one: "{{count}} thing", count_other: "{{count}} things", extra: "X" };
    expect(compareNamespace("demo", source, target, "en")).toEqual([
      'en/demo: missing key "nested.a"',
      'en/demo: extra key "extra" not in Spanish',
    ]);
  });

  it("reports variables that differ between languages", () => {
    const target: Resource = { title: "Hello {{user}}", count_one: "{{count}} thing", count_other: "{{count}} things", nested: { a: "A" } };
    expect(compareNamespace("demo", source, target, "en")).toEqual([
      'en/demo: "title" uses variables [user] but Spanish uses [name]',
    ]);
  });

  it("reports a plural without its other form and an empty value", () => {
    const target: Resource = { title: "Hello {{name}}", count_one: "{{count}} thing", nested: { a: " " } };
    expect(compareNamespace("demo", source, target, "en")).toEqual([
      'en/demo: plural "count" lacks the "_other" form',
      'en/demo: "nested.a" is empty',
    ]);
  });
});

describe("helpers", () => {
  it("lists variables once, ignoring formats", () => {
    expect(variablesOf("{{a}} y {{ b, number }} y {{a}}")).toEqual(["a", "b"]);
  });

  it("flattens nested namespaces", () => {
    expect([...flatten({ a: { b: "1" }, c: "2" }).keys()]).toEqual(["a.b", "c"]);
  });

  it("asks for one and other in English and Spanish", () => {
    expect(requiredPluralForms("en")).toEqual(["one", "other"]);
    expect(requiredPluralForms("es")).toEqual(["one", "other"]);
  });
});

describe("findHardcodedSpanish", () => {
  it("flags accented text, JSX text and common Spanish words", () => {
    const source = [
      'const a = "Configuración";',
      "const b = <p>Guardar cambios</p>;",
      'const c = `Hola ${name}, ¿cómo estás?`;',
      'const d = "Cancelar";',
    ].join("\n");
    expect(findHardcodedSpanish(source).map((finding) => finding.line)).toEqual([1, 2, 3, 4]);
  });

  it("ignores English, identifiers, import paths, comments and marked lines", () => {
    const source = [
      'import x from "../copy/es";',
      "// Texto en español en un comentario",
      'const a = "Save changes";',
      'const b = "Año"; // i18n-ignore',
      'const c = { className: "meeting-list" };',
    ].join("\n");
    expect(findHardcodedSpanish(source)).toEqual([]);
  });

  it("exempts translations, tests and the checker", () => {
    expect(isExemptFromSpanishCheck("/x/src/locales/es/shell.json")).toBe(true);
    expect(isExemptFromSpanishCheck("/x/src/components/Foo.test.tsx")).toBe(true);
    expect(isExemptFromSpanishCheck("/x/src/components/Foo.tsx")).toBe(false);
  });
});
