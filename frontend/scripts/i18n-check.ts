import { existsSync, readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative } from "node:path";
import {
  checkSourcePlurals, compareNamespace, findHardcodedSpanish, isExemptFromSpanishCheck, type Resource,
} from "../src/i18n/check";

// Usage: npm run i18n:check  (exits 1 and lists every problem when a translation or a source file is off)
const root = join(import.meta.dirname, "..");
const localesDir = join(root, "src", "locales");
const sourceLanguage = "es";

function readNamespaces(language: string): Record<string, Resource> {
  const dir = join(localesDir, language);
  const out: Record<string, Resource> = {};
  for (const file of readdirSync(dir).filter((name) => name.endsWith(".json")).sort()) {
    out[file.slice(0, -".json".length)] = JSON.parse(readFileSync(join(dir, file), "utf8")) as Resource;
  }
  return out;
}

function sourceFiles(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) return sourceFiles(path);
    return /\.tsx?$/.test(name) ? [path] : [];
  });
}

const problems: string[] = [];
const source = readNamespaces(sourceLanguage);
for (const [namespace, resource] of Object.entries(source)) problems.push(...checkSourcePlurals(namespace, resource));
const languages = readdirSync(localesDir).filter((name) => name !== sourceLanguage && statSync(join(localesDir, name)).isDirectory());
for (const language of languages) {
  const target = readNamespaces(language);
  for (const namespace of new Set([...Object.keys(source), ...Object.keys(target)])) {
    if (!source[namespace]) problems.push(`${language}/${namespace}: namespace does not exist in Spanish`);
    else if (!target[namespace]) problems.push(`${language}/${namespace}: namespace is missing`);
    else problems.push(...compareNamespace(namespace, source[namespace], target[namespace], language));
  }
}
if (existsSync(join(root, "src"))) {
  for (const file of sourceFiles(join(root, "src"))) {
    if (isExemptFromSpanishCheck(file)) continue;
    for (const finding of findHardcodedSpanish(readFileSync(file, "utf8"), file)) {
      problems.push(`${relative(root, file)}:${finding.line}: Spanish text outside src/locales: "${finding.text}"`);
    }
  }
}

if (problems.length > 0) {
  console.error(`i18n:check found ${problems.length} problem(s):`);
  for (const problem of problems) console.error(`  ${problem}`);
  process.exit(1);
}
console.log(`i18n:check ok (${Object.keys(source).length} namespaces, languages: ${[sourceLanguage, ...languages].join(", ")})`);
