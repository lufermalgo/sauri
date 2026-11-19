/**
 * A model's license as people write it («MIT», «Apache 2.0», «CC BY 4.0») from the identifier the catalog or Hugging
 * Face gives («mit», «apache-2.0», «CC-BY-4.0»). Only identifiers whose usual name is certain are rewritten; any other
 * one is shown as it came, never guessed.
 */
const NAMES: Record<string, string> = {
  mit: "MIT",
  isc: "ISC",
  unlicense: "The Unlicense",
  "apache-2.0": "Apache 2.0",
  "bsd-2-clause": "BSD 2-Clause",
  "bsd-3-clause": "BSD 3-Clause",
  "mpl-2.0": "MPL 2.0",
  "cc0-1.0": "CC0 1.0",
  "artistic-2.0": "Artistic 2.0",
  gemma: "Gemma Terms of Use",
  openrail: "OpenRAIL",
};

/** cc-by-4.0, cc-by-nc-sa-4.0, CC-BY-SA-3.0... */
const CREATIVE_COMMONS = /^cc-(by(?:-(?:sa|nc|nd))*)-(\d\.\d)$/;
/** gpl-3.0, lgpl-2.1, agpl-3.0, with the SPDX «-only» or «-or-later» ending. */
const GNU = /^((?:a|l)?gpl)-(\d\.\d)(-only|-or-later)?$/;
/** llama2, llama3.1... (Meta's license names). */
const LLAMA = /^llama(\d(?:\.\d)?)$/;

export function licenseName(id: string): string {
  const key = id.trim().toLowerCase();
  const known = NAMES[key];
  if (known) return known;
  const cc = CREATIVE_COMMONS.exec(key);
  if (cc) return `CC ${cc[1].toUpperCase()} ${cc[2]}`;
  const gnu = GNU.exec(key);
  if (gnu) return `${gnu[1].toUpperCase()} ${gnu[2]}${gnu[3] === "-or-later" ? "+" : ""}`;
  const llama = LLAMA.exec(key);
  if (llama) return `Llama ${llama[1]} Community License`;
  return id;
}
