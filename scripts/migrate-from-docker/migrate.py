"""Entry point: `cd backend && uv run python ../scripts/migrate-from-docker/migrate.py --dry-run ...`."""

import sys
from pathlib import Path

# The backend package (`app`) comes from the uv environment; this folder holds `sauri_migrate`.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from sauri_migrate.cli import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
