"""Operator tool: copy a model bundle that is already on this Mac into the managed models directory.

    python seed_model.py <model-id> <source-directory>

Every source file is checked against the catalog (size and SHA-256) while it is copied; the source is not
changed. Used by ``scripts/engines/install-parakeet-engine.sh --adopt-from`` so an existing download is not
fetched again. No network access.
"""

from __future__ import annotations

import sys
from pathlib import Path

from local_models import LocalModelError, LocalModelService, seed_bundle


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print("usage: seed_model.py <model-id> <source-directory>", file=sys.stderr)
        return 2
    try:
        outcome = seed_bundle(LocalModelService(), argv[1], Path(argv[2]).expanduser())
    except LocalModelError as error:
        print(f"seed failed: {error.code}", file=sys.stderr)
        return 1
    print(f"{argv[1]}: {outcome}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
