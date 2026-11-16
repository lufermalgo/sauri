"""Command-contract tests for compose-bringup.sh, using explicit Docker/HTTP doubles.

They exercise ordering and failure handling, not live infrastructure or inference.
Only fixture files and synthetic credentials under a temporary HOME are used.
"""

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT_NAME = "scripts/platform/compose-bringup.sh"
MAKEFILE_NAME = "Makefile"


def logical_calls(lines, prefix):
    """Merge continuation lines (multi-line `sh -c` scripts) into the call that started them."""
    calls = []
    for line in lines:
        if line.startswith(prefix):
            calls.append(line)
        else:
            calls[-1] += "\n" + line
    return calls


SETUP_PREFIX = [
    "stop api worker",
    "up -d postgres minio rabbitmq",
    "exec -T postgres pg_isready -U sauri -d sauri -q",
    "exec -T postgres psql -v ON_ERROR_STOP=1 -q -U sauri -d sauri",
    "exec -T rabbitmq rabbitmqctl -q await_startup",
]


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
            shutil.copytree(ROOT, tree, ignore=shutil.ignore_patterns(".git", ".worktrees", "__pycache__", "node_modules", "dist", ".env*"))
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
                calls = logical_calls(log.read_text().splitlines(), "compose ")
            finally:
                os.chdir(ROOT)

        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertIn("migration", result.stderr.lower(), result.stderr)
        commands = [call.removeprefix("compose ") for call in calls]
        self.assertEqual(commands[:len(SETUP_PREFIX)], SETUP_PREFIX, calls)
        self.assertTrue(commands[len(SETUP_PREFIX)].startswith("exec -T rabbitmq sh -c"), calls)
        self.assertEqual(commands[len(SETUP_PREFIX) + 1], "run --rm api python -m app.infra.ensure_bucket", calls)
        self.assertEqual(commands[len(SETUP_PREFIX) + 2], "run --rm api alembic upgrade head", calls)
        self.assertNotIn("compose up -d api worker portal", calls)

    def test_success_starts_applications_only_after_setup(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            tree = Path(temp_dir) / "tree"
            shutil.copytree(ROOT, tree, ignore=shutil.ignore_patterns(".git", ".worktrees", "__pycache__", "node_modules", "dist", ".env*"))
            (tree / SCRIPT_NAME).write_text(Path(ROOT / SCRIPT_NAME).read_text())
            (tree / SCRIPT_NAME).chmod(0o755)
            os.chdir(tree)
            try:
                docker = tree / "docker"
                log = tree / "calls"
                docker.write_text("#!/bin/sh\nprintf '%s\\n' \"$*\" >> \"$CALL_LOG\"\ncase \"$*\" in *'port portal 80'*) echo 127.0.0.1:15173;; esac\n")
                curl = tree / "curl"
                curl.write_text("#!/bin/sh\necho 200\n")
                curl.chmod(0o755)
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
            calls.index("compose up -d api worker portal"),
        )
        seed = "compose run --rm api python -m app.auth.seed_admin --retire-legacy"
        self.assertLess(calls.index("compose run --rm api alembic upgrade head"), calls.index(seed))
        self.assertLess(calls.index(seed), calls.index("compose up -d api worker portal"))

    def test_make_up_invokes_bringup_script(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            tree = Path(temp_dir) / "tree"
            shutil.copytree(ROOT, tree, ignore=shutil.ignore_patterns(".git", ".worktrees", "__pycache__", "node_modules", "dist", ".env*"))
            os.chdir(tree)
            try:
                docker = tree / "docker"
                log = tree / "calls"
                docker.write_text("#!/bin/sh\nprintf '%s\\n' \"$*\" >> \"$CALL_LOG\"\ncase \"$*\" in *'port portal 80'*) echo 127.0.0.1:15173;; esac\n")
                curl = tree / "curl"
                curl.write_text("#!/bin/sh\necho 200\n")
                curl.chmod(0o755)
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
            calls.index("compose up -d api worker portal"),
        )


class PortalBringupContractTests(unittest.TestCase):
    def run_bringup(self, failure=""):
        with tempfile.TemporaryDirectory() as temp_dir:
            tree = Path(temp_dir)
            for relative in [SCRIPT_NAME, "scripts/engines/ensure-native-engine-credentials.sh"]:
                (tree / relative).parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(ROOT / relative, tree / relative)
            docker = tree / "docker"
            docker.write_text('''#!/bin/sh
printf '%s|%s|%s\\n' "$COMPOSE_PROJECT_NAME" "$COMPOSE_FILE" "$*" >> "$CALL_LOG"
case "$*" in
  *"$FAIL_DOCKER"*) if [ -n "$FAIL_DOCKER" ]; then exit 17; fi;;
esac
case "$*" in *'port portal 80'*) echo 127.0.0.1:15173;; esac
''')
            docker.chmod(0o755)
            curl = tree / "curl"
            curl.write_text('''#!/bin/sh
printf '%s\\n' "$*" >> "$HTTP_LOG"
case "$*" in *"$FAIL_HTTP"*) if [ -n "$FAIL_HTTP" ]; then exit 22; fi;; esac
echo 200
''')
            curl.chmod(0o755)
            log, http_log = tree / "calls", tree / "http"
            env = os.environ | {
                "PATH": f"{tree}:{os.environ['PATH']}", "HOME": str(tree),
                "CALL_LOG": str(log), "HTTP_LOG": str(http_log),
                "COMPOSE_PROJECT_NAME": "sauri-local-qa-123456abcdef",
                "COMPOSE_FILE": "base.yml:qa.yml", "PORTAL_PORT": "9999",
                "FAIL_DOCKER": failure if failure != "api-health" else "",
                "FAIL_HTTP": failure if failure == "api-health" else "",
            }
            result = subprocess.run(["bash", str(tree / SCRIPT_NAME)], cwd=tree,
                                    env=env, text=True, capture_output=True, timeout=70)
            calls = log.read_text().splitlines() if log.exists() else []
            http_calls = http_log.read_text().splitlines() if http_log.exists() else []
            # Bring-up is never allowed to remove a volume or run global cleanup.
            self.assertFalse(any("prune" in line or "down" in line or "clean" in line for line in calls))
            return result, calls, http_calls

    def test_selected_project_and_files_apply_even_to_stop(self):
        result, calls, http_calls = self.run_bringup()
        self.assertEqual(result.returncode, 0, result.stderr)
        prefix = "sauri-local-qa-123456abcdef|base.yml:qa.yml|compose "
        calls = logical_calls(calls, prefix)
        commands = [line.removeprefix(prefix) for line in calls]
        self.assertTrue(commands[len(SETUP_PREFIX)].startswith("exec -T rabbitmq sh -c"), calls)
        del commands[len(SETUP_PREFIX)]
        self.assertEqual(commands, SETUP_PREFIX + [
                         "run --rm api python -m app.infra.ensure_bucket",
                         "run --rm api alembic upgrade head",
                         "run --rm api python -m app.auth.seed_admin --retire-legacy",
                         "up -d api worker portal",
                         "port portal 80"])
        self.assertEqual(len(http_calls), 2)
        self.assertIn("http://127.0.0.1:15173/portal-health", http_calls[0])
        self.assertIn("http://127.0.0.1:15173/api-health", http_calls[1])
        self.assertNotIn(":9999", "\n".join(http_calls))
        self.assertIn("inference not verified", result.stdout)

    def test_bucket_failure_prevents_migration_and_final_start(self):
        result, calls, http_calls = self.run_bringup("app.infra.ensure_bucket")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("bucket", result.stderr)
        self.assertFalse(any("alembic" in line or "up -d api" in line for line in calls))
        self.assertFalse(http_calls)
        self.assertNotIn("ready:", result.stdout)

    def test_migration_failure_prevents_final_start_and_http(self):
        result, calls, http_calls = self.run_bringup("alembic upgrade head")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("migrations", result.stderr)
        self.assertFalse(any("up -d api" in line for line in calls))
        self.assertFalse(http_calls)
        self.assertNotIn("ready:", result.stdout)

    def test_failed_final_start_prevents_http_and_success(self):
        result, calls, http_calls = self.run_bringup("up -d api worker portal")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("starting API, worker and portal", result.stderr)
        self.assertFalse(any("port portal 80" in line for line in calls))
        self.assertFalse(http_calls)
        self.assertNotIn("ready:", result.stdout)

    def test_failed_binding_lookup_prevents_http_and_success(self):
        result, _, http_calls = self.run_bringup("port portal 80")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("published address", result.stderr)
        self.assertFalse(http_calls)
        self.assertNotIn("ready:", result.stdout)

    def test_portal_alone_never_proves_api_availability(self):
        import time
        start = time.monotonic()
        result, _, http_calls = self.run_bringup("api-health")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("api-health", result.stderr)
        self.assertNotIn("ready:", result.stdout)
        self.assertTrue(any("/portal-health" in line for line in http_calls))
        self.assertLess(time.monotonic() - start, 65)


if __name__ == "__main__":
    unittest.main()
