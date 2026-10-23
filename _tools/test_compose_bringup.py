"""RED tests for _tools/compose-bringup.sh.

These tests run against a local /tmp copy of the repository tree where _tools/ and
the Makefile/dstk paths are rewritten to match, because the real script calls
`docker compose`, which is unavailable/uncapable in this environment.
"""

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
SCRIPT_NAME = "_tools/compose-bringup.sh"
MAKEFILE_NAME = "Makefile"


class ComposeBringupTests(unittest.TestCase):
    def test_volume_repair_has_capabilities_for_fresh_volume_permissions(self):
        compose = (ROOT / "docker-compose.yml").read_text()
        repair_service = compose.split("  minio-volume-permissions:\n", 1)[1].split("\n  # --- MinIO", 1)[0]

        self.assertIn('cap_add: ["CHOWN", "DAC_OVERRIDE"]', repair_service)

    def test_volume_repair_has_no_network_access(self):
        compose = (ROOT / "docker-compose.yml").read_text()
        repair_service = compose.split("  minio-volume-permissions:\n", 1)[1].split("\n  # --- MinIO", 1)[0]

        self.assertIn("network_mode: none", repair_service)

    def test_setup_runs_before_api_and_reports_failed_migration(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            tree = Path(temp_dir) / "tree"
            shutil.copytree(ROOT, tree, ignore=shutil.ignore_patterns(".git", ".worktrees", "__pycache__"))
            (tree / SCRIPT_NAME).write_text(Path(ROOT / SCRIPT_NAME).read_text())
            (tree / SCRIPT_NAME).chmod(0o755)
            # Set HOME to the temp tree so the "engine token" bind path doesn't touch the host.
            os.chdir(tree)
            try:
                docker = tree / "docker"
                log = tree / "calls"
                docker.write_text(
                    "#!/bin/sh\nprintf '%s\\n' \"$*\" >> \"$CALL_LOG\"\n"
                    "case \"$*\" in *'run --rm api alembic upgrade head'*) exit 17;; esac\n"
                )
                docker.chmod(0o755)
                env = os.environ | {
                    "PATH": f"{tree}:{os.environ['PATH']}",
                    "HOME": str(tree),
                    "CALL_LOG": str(log),
                }
                result = subprocess.run([str(tree / SCRIPT_NAME)], cwd=tree, env=env, text=True, capture_output=True)
                calls = log.read_text().splitlines()
            finally:
                os.chdir(ROOT)

        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertIn("migration", result.stderr.lower(), result.stderr)
        self.assertEqual(calls[0], "compose stop api worker", calls)
        self.assertEqual(calls[1], "compose up -d postgres minio rabbitmq", calls)
        self.assertEqual(calls[2], "compose run --rm api python -m app.infra.ensure_bucket", calls)
        self.assertEqual(calls[3], "compose run --rm api alembic upgrade head", calls)
        self.assertNotIn("compose up -d api worker", calls)

    def test_success_starts_applications_only_after_setup(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            tree = Path(temp_dir) / "tree"
            shutil.copytree(ROOT, tree, ignore=shutil.ignore_patterns(".git", ".worktrees", "__pycache__"))
            (tree / SCRIPT_NAME).write_text(Path(ROOT / SCRIPT_NAME).read_text())
            (tree / SCRIPT_NAME).chmod(0o755)
            os.chdir(tree)
            try:
                docker = tree / "docker"
                log = tree / "calls"
                docker.write_text("#!/bin/sh\nprintf '%s\\n' \"$*\" >> \"$CALL_LOG\"\n")
                docker.chmod(0o755)
                env = os.environ | {
                    "PATH": f"{tree}:{os.environ['PATH']}",
                    "HOME": str(tree),
                    "CALL_LOG": str(log),
                }
                result = subprocess.run([str(tree / SCRIPT_NAME)], cwd=tree, env=env, text=True, capture_output=True)
                calls = log.read_text().splitlines()
            finally:
                os.chdir(ROOT)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertLess(
            calls.index("compose run --rm api alembic upgrade head"),
            calls.index("compose up -d api worker"),
        )

    def test_make_up_invokes_bringup_script(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            tree = Path(temp_dir) / "tree"
            shutil.copytree(ROOT, tree, ignore=shutil.ignore_patterns(".git", ".worktrees", "__pycache__"))
            os.chdir(tree)
            try:
                docker = tree / "docker"
                log = tree / "calls"
                docker.write_text("#!/bin/sh\nprintf '%s\\n' \"$*\" >> \"$CALL_LOG\"\n")
                docker.chmod(0o755)
                env = os.environ | {
                    "PATH": f"{tree}:{os.environ['PATH']}",
                    "HOME": str(tree),
                    "CALL_LOG": str(log),
                }
                result = subprocess.run(["make", "up"], cwd=tree, env=env, text=True, capture_output=True)
                calls = log.read_text().splitlines() if log.exists() else []
            finally:
                os.chdir(ROOT)

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertLess(
            calls.index("compose run --rm api alembic upgrade head"),
            calls.index("compose up -d api worker"),
        )


if __name__ == "__main__":
    unittest.main()
