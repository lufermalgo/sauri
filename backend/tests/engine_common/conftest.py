"""Load the standalone native engine helpers without installing them in the API."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "engine-common"))
