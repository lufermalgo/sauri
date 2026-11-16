import { describe, expect, it } from "vitest";
import { titleToFilename } from "./download-filename";

describe("titleToFilename", () => {
  it("appends the extension to a normal title", () => {
    expect(titleToFilename("Weekly sync", "txt")).toBe("Weekly sync.txt");
  });

  it("keeps accents and the letter n with tilde", () => {
    expect(titleToFilename("Caf\u00e9 planning a\u00f1o 2026", "txt")).toBe("Caf\u00e9 planning a\u00f1o 2026.txt");
  });

  it("replaces forbidden characters and control characters", () => {
    expect(titleToFilename('a\\b/c:d*e?f"g<h>i|j\u0000k\u001fl', "txt")).toBe("a b c d e f g h i j k l.txt");
  });

  it("collapses whitespace and trims spaces and dots at the edges", () => {
    expect(titleToFilename("  ..  Many   spaced \t words ..  ", "txt")).toBe("Many spaced words.txt");
  });

  it("limits the base name to 120 characters", () => {
    const name = titleToFilename("a".repeat(300), "txt");
    expect(name).toBe(`${"a".repeat(120)}.txt`);
  });

  it("does not leave a trailing space where the title was cut", () => {
    const name = titleToFilename(`${"a".repeat(119)} bbb`, "txt");
    expect(name).toBe(`${"a".repeat(119)}.txt`);
  });

  it("does not split a surrogate pair at the length limit", () => {
    const name = titleToFilename(`${"a".repeat(119)}😀😀`, "txt");
    expect(name).toBe(`${"a".repeat(119)}😀.txt`);
    expect(name).not.toMatch(/[\uD800-\uDBFF](?![\uDC00-\uDFFF])|(?<![\uD800-\uDBFF])[\uDC00-\uDFFF]/);
  });

  it.each([null, undefined, "", "   ", "...", "///", ' :*?"<>| '])("returns null for an empty result (%j)", title => {
    expect(titleToFilename(title, "txt")).toBeNull();
  });

  it.each(["CON", "nul", "Aux", "PRN", "COM1", "lpt9"])("avoids the reserved Windows name %s", title => {
    expect(titleToFilename(title, "txt")).toBe(`_${title}.txt`);
  });

  it("avoids a reserved name followed by dots", () => {
    expect(titleToFilename("nul.backup", "txt")).toBe("_nul.backup.txt");
  });

  it("keeps names that only start like a reserved name", () => {
    expect(titleToFilename("console", "txt")).toBe("console.txt");
    expect(titleToFilename("COM10", "txt")).toBe("COM10.txt");
  });

  it.each(["webm", "mp4", "m4a", "mp3", "wav", "mov", "mkv", "ogg", "opus", "WEBM"])("strips the media extension %s", ext => {
    expect(titleToFilename(`recording.${ext}`, "txt")).toBe("recording.txt");
  });

  it("strips only one trailing media extension", () => {
    expect(titleToFilename("recording.mp4.webm", "txt")).toBe("recording.mp4.txt");
  });

  it("keeps other extensions as part of the name", () => {
    expect(titleToFilename("notes.v2", "txt")).toBe("notes.v2.txt");
  });

  it("returns null when the title is only a media extension", () => {
    expect(titleToFilename(".webm", "txt")).toBeNull();
  });
});
