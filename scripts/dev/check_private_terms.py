#!/usr/bin/env python3
"""Fails when a tracked (or staged) file leaks private data. Rule "Public-safe content" in AGENTS.md.

Two layers:
  1. A private denylist that is never committed (a list in the repository would publish what it protects).
     Read from $SAURI_PRIVATE_TERMS, else `.private-terms.txt` in the main checkout (gitignored).
     No file: the layer passes silently (CI, fresh clones). One entry per line:
       term            matched as a whole word, ignoring case and accents
       re:<regex>      a Python regex, case-insensitive
       allow:<text>    a line containing this text is never reported
       # comment
  2. Public shapes that run everywhere: absolute home paths of a real-looking user and credential shapes.

Usage:
    check_private_terms.py            # every tracked file
    check_private_terms.py --staged   # only staged files (pre-commit)
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import unicodedata
from pathlib import Path

MAX_BYTES = 2 * 1024 * 1024
SKIPPED_FILES = {"package-lock.json", "backend/uv.lock"}
# Placeholder home folders that tests and docs may use.
PLACEHOLDER_USERS = {
    "x", "a", "me", "you", "user", "username", "name", "test", "demo", "ana", "private", "someone", "shared",
    "external", "disco", "sauri", "acme", "example",
}
HOME_PATH = re.compile(r"/(?:Users|home|Volumes)/([A-Za-z0-9._-]+)")
CREDENTIALS = re.compile(
    r"gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,}|sk-ant-[A-Za-z0-9_-]{20,}|AKIA[0-9A-Z]{16}"
    r"|AIza[0-9A-Za-z_-]{35}|xox[baprs]-[A-Za-z0-9-]{10,}|-----BEGIN [A-Z ]*PRIVATE KEY-----"
)


def fold(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", text) if unicodedata.category(c) != "Mn").lower()


def parse_terms(text: str) -> tuple[list[tuple[str, re.Pattern[str]]], list[str]]:
    matchers: list[tuple[str, re.Pattern[str]]] = []
    allow: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("allow:"):
            allow.append(fold(line[6:].strip()))
        elif line.startswith("re:"):
            matchers.append((line, re.compile(line[3:].strip(), re.IGNORECASE)))
        else:
            matchers.append((line, re.compile(rf"(?<![\w]){re.escape(fold(line))}(?![\w])")))
    return matchers, allow


def main_checkout() -> Path:
    common = subprocess.run(
        ["git", "rev-parse", "--path-format=absolute", "--git-common-dir"], capture_output=True, text=True, check=True
    ).stdout.strip()
    return Path(common).parent


def terms_file() -> Path | None:
    env = os.environ.get("SAURI_PRIVATE_TERMS")
    if env:
        return Path(env) if Path(env).is_file() else None
    candidate = main_checkout() / ".private-terms.txt"
    return candidate if candidate.is_file() else None


def files_to_scan(staged: bool) -> list[str]:
    args = ["git", "diff", "--cached", "--name-only", "--diff-filter=ACMR"] if staged else ["git", "ls-files"]
    out = subprocess.run(args, capture_output=True, text=True, check=True).stdout
    return [f for f in out.splitlines() if f and f not in SKIPPED_FILES]


def scan_line(line: str, matchers: list[tuple[str, re.Pattern[str]]], allow: list[str]) -> list[str]:
    folded = fold(line)
    if any(a and a in folded for a in allow):
        return []
    found = [label for label, rx in matchers if rx.search(folded if not label.startswith("re:") else line)]
    for match in HOME_PATH.finditer(line):
        if match.group(1).lower() not in PLACEHOLDER_USERS:
            found.append(f"absolute path of a real user ({match.group(0)}); use ~/ or a placeholder")
    if CREDENTIALS.search(line):
        found.append("credential-shaped text")
    return found


def main(argv: list[str]) -> int:
    staged = "--staged" in argv
    source = terms_file()
    matchers, allow = parse_terms(source.read_text(encoding="utf-8")) if source else ([], [])
    root = Path(subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True,
                               check=True).stdout.strip())
    hits = 0
    for name in files_to_scan(staged):
        path = root / name
        if not path.is_file() or path.is_symlink() or path.stat().st_size > MAX_BYTES:
            continue
        data = path.read_bytes()
        if b"\0" in data[:8000]:
            continue
        for number, line in enumerate(data.decode("utf-8", "replace").splitlines(), 1):
            for label in scan_line(line, matchers, allow):
                # Never echo the private term itself: the output may end up in a public CI log.
                shown = "a private term" if not label.startswith(("absolute", "credential")) else label
                print(f"{name}:{number}: {shown}")
                hits += 1
    if hits:
        print(f"check_private_terms: {hits} finding(s). Replace them with placeholders (Acme, user@example.com, ~/...).",
              file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
