"""Tests of scripts/migrate-from-docker (the one-time move from the Docker installation)."""

import sys
from pathlib import Path

TOOL_DIR = Path(__file__).resolve().parents[3] / "scripts" / "migrate-from-docker"
if str(TOOL_DIR) not in sys.path:
    sys.path.insert(0, str(TOOL_DIR))
