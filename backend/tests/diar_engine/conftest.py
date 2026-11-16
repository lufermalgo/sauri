"""Load the standalone native engine helpers without installing them in the API."""

import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2]
# The gateway imports its sibling ``diar_external`` as a top-level module, as it does when launched with --app-dir.
sys.path[:0] = [str(BACKEND / "diar-engine"), str(BACKEND / "engine-common")]
