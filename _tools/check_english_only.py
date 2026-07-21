#!/usr/bin/env python3
"""Language_Regression_Check — flags Spanish identifiers in new/modified code.

Part of the english-codebase-standard spec
(.spectra/specs/english-codebase-standard/design.md > Decisiones de Diseño
Clave > "Language_Regression_Check como un único script...").

Usage:
    check_english_only.py <path> [<path> ...]
    check_english_only.py --staged   # scans `git diff --cached --name-only`

Exits 1 and prints "<file>:<line>: <match>" per finding when any Spanish
identifier is found; exits 0 otherwise.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

EXCLUDED_PATH_PARTS = (
    ".spectra/specs/",
    "/fixtures/",
    "/.venv/",
    "/node_modules/",
    "/__pycache__/",
)

# Requisito 1.1 / 7.1: only these trees are governed by the English-only standard.
INCLUDED_PATH_PREFIXES = (
    "backend/",
    "extension/src/",
    "frontend/src/",
    "packages/shared-types/",
)


def is_in_scope(path: str) -> bool:
    normalized = path.replace("\\", "/")
    return any(normalized.startswith(prefix) for prefix in INCLUDED_PATH_PREFIXES)

SPANISH_SAMPLE_DATA_MARKER = "spanish-sample-data"

IDENTIFIER_PATTERN = re.compile(r"[a-zA-Z_][a-zA-Z0-9_áéíóúñÁÉÍÓÚÑ]*")
ACCENT_PATTERN = re.compile(r"[áéíóúñÁÉÍÓÚÑ]")

# Populated from the "Español" columns of design.md > Componentes e Interfaces.
RETIRED_SPANISH_TERMS = [
    "reunion",
    "reuniones",
    "hablante",
    "hablantes",
    "transcripcion",
    "transcripciones",
    "diarizacion",
    "diarizaciones",
    "grabacion",
    "grabaciones",
    "usuario",
    "usuarios",
    "obtener_",
    "crear_",
    "listar_",
    "eliminar_",
    "renombrar_",
    "solicitar_",
    "registrar_",
    "actualizar_",
    "procesar_",
    "validar_",
    "verificar_",
    "asignar_",
    "etiquetar_",
    "sembrar_",
    "estado_proceso",
    "causa_fallo",
    "es_comercial",
    "clave_idempotencia",
    "duracion_segundos",
    "creada_en",
    "creado_en",
    "ocurrido_en",
]

_RETIRED_TERMS_PATTERN = re.compile(
    "(" + "|".join(re.escape(term) for term in RETIRED_SPANISH_TERMS) + ")",
    re.IGNORECASE,
)


def _is_flagged_identifier(identifier: str) -> bool:
    if ACCENT_PATTERN.search(identifier):
        return True
    return bool(_RETIRED_TERMS_PATTERN.search(identifier))


def is_excluded_path(path: str) -> bool:
    normalized = path.replace("\\", "/")
    return any(part in f"/{normalized}" for part in EXCLUDED_PATH_PARTS)


def staged_files() -> list[str]:
    result = subprocess.run(
        ["git", "diff", "--cached", "--name-only", "--diff-filter=ACMR"],
        capture_output=True,
        text=True,
        check=True,
    )
    return [line for line in result.stdout.splitlines() if line.strip()]


def find_matches_in_line(line: str) -> list[str]:
    seen: set[str] = set()
    unique: list[str] = []
    for token_match in IDENTIFIER_PATTERN.finditer(line):
        identifier = token_match.group(0)
        if identifier in seen:
            continue
        if _is_flagged_identifier(identifier):
            seen.add(identifier)
            unique.append(identifier)
    return unique


def scan_file(path: Path) -> list[tuple[int, str]]:
    findings: list[tuple[int, str]] = []
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except (FileNotFoundError, IsADirectoryError):
        return findings

    for lineno, line in enumerate(text.splitlines(), start=1):
        if SPANISH_SAMPLE_DATA_MARKER in line:
            continue
        for match in find_matches_in_line(line):
            findings.append((lineno, match))
    return findings


def main(argv: list[str]) -> int:
    if argv and argv[0] == "--staged":
        # --staged scans the whole repo's diff, so scope it to the trees this
        # standard governs (Requisito 1.1 / 7.1) — e.g. Makefile or _tools/
        # itself are out of scope and shouldn't block unrelated commits.
        paths = [p for p in staged_files() if is_in_scope(p) and not is_excluded_path(p)]
    else:
        # Explicit path arguments are scanned as given (callers — tests, or a
        # `make check-english` invocation already scoped via its own globs —
        # decide what's in scope).
        paths = [p for p in argv if not is_excluded_path(p)]

    had_findings = False
    for raw_path in paths:
        path = Path(raw_path)
        for lineno, match in scan_file(path):
            print(f"{raw_path}:{lineno}: {match}")
            had_findings = True

    return 1 if had_findings else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
