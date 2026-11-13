"""Ownership/lifecycle contract tests with Docker doubles, not live integration."""
import base64
import importlib.util
import json
from pathlib import Path
import socket
import tempfile
import unittest
from unittest.mock import patch

PATH = Path(__file__).with_name('validate-local-platform.py')


class ValidationLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(PATH.exists(), 'Missing QA create/check/cleanup implementation')
        spec = importlib.util.spec_from_file_location('local_validation', PATH)
        self.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.module)

    def inventory(self):
        return {'schemaVersion': 1, 'runId': '123456abcdef',
                'projectName': 'sauri-local-qa-123456abcdef',
                'resourceIds': {'containers': ['owned'], 'networks': [], 'volumes': []}}

    def test_ownership_matrix_requires_inventory_id_and_both_labels(self):
        module = self.module
        for index in range(120):
            recorded = index % 2 == 0
            correct_project = index % 3 != 0
            correct_run = index % 5 != 0
            inventory = self.inventory()
            identity = 'owned' if recorded else 'foreign-' + str(index)
            labels = {'com.docker.compose.project': inventory['projectName'] if correct_project else 'foreign',
                      'sauri.validation.run': inventory['runId'] if correct_run else 'foreign'}
            with self.subTest(index=index):
                self.assertEqual(module.owns(inventory, 'containers', identity, labels),
                                 recorded and correct_project and correct_run)
        self.assertFalse(module.owns(None, 'containers', 'owned', {}))

    def test_invalid_or_missing_inventory_never_deletes(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'inventory.json'
            with patch.object(self.module, 'docker') as docker:
                with self.assertRaises((ValueError, FileNotFoundError)):
                    self.module.cleanup(path)
                for field, value in [('runId', 'bad'), ('projectName', 'sauri'), ('schemaVersion', 2)]:
                    inventory = self.inventory()
                    inventory[field] = value
                    path.write_text(json.dumps(inventory))
                    with self.assertRaises(ValueError):
                        self.module.cleanup(path)
                docker.assert_not_called()

    def test_foreign_resource_preflight_rejects_all_deletion(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'inventory.json'
            path.write_text(json.dumps(self.inventory()))
            with patch.object(self.module, 'inspect_resource', return_value={'com.docker.compose.project': 'foreign'}), \
                 patch.object(self.module, 'docker') as docker:
                with self.assertRaises(ValueError):
                    self.module.cleanup(path)
                docker.assert_not_called()

    def test_owned_resources_are_removed_in_dependency_order(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'inventory.json'
            inventory = self.inventory()
            inventory['resourceIds'] = {'containers': ['c'], 'networks': ['n'], 'volumes': ['v']}
            path.write_text(json.dumps(inventory))
            labels = {'com.docker.compose.project': inventory['projectName'],
                      'sauri.validation.run': inventory['runId']}
            empty = {'containers': [], 'networks': [], 'volumes': []}
            with patch.object(self.module, 'inspect_resource', return_value=labels), \
                 patch.object(self.module, 'discover', side_effect=[inventory['resourceIds'], empty]), \
                 patch.object(self.module, 'docker') as docker:
                self.module.cleanup(path)
                self.assertEqual([call.args for call in docker.call_args_list], [
                    ('container', 'rm', '-f', 'c'), ('network', 'rm', 'n'), ('volume', 'rm', 'v')])
            self.assertEqual(json.loads(path.read_text())['cleanup'], 'verified')

    def test_cleanup_missing_resources_is_idempotent(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'inventory.json'
            path.write_text(json.dumps(self.inventory()))
            with patch.object(self.module, 'inspect_resource', return_value=None), \
                 patch.object(self.module, 'discover', return_value={'containers': [], 'networks': [], 'volumes': []}), \
                 patch.object(self.module, 'docker') as docker:
                self.module.cleanup(path)
                self.module.cleanup(path)
                docker.assert_not_called()
            self.assertEqual(json.loads(path.read_text())['cleanup'], 'verified')

    def test_port_collision_selects_another_block_without_stopping_occupant(self):
        with socket.socket() as listener:
            listener.bind(('127.0.0.1', 0))
            listener.listen()
            occupied = listener.getsockname()[1]
            ports = self.module.select_ports({'portal': occupied}, attempts=2)
            self.assertNotEqual(ports['portal'], occupied)
            with self.assertRaises(RuntimeError):
                self.module.select_ports({'portal': occupied}, attempts=1)

    def test_override_and_synthetic_secrets_never_mount_owner_files(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            with patch.object(self.module, 'validate_config'), \
                 patch.object(self.module, 'discover', return_value={'containers': [], 'networks': [], 'volumes': []}):
                path = self.module.create(directory)
            inventory = json.loads(path.read_text())
            self.module.validate_inventory(inventory)
            self.assertEqual(inventory['resourceIds'], {'containers': [], 'networks': [], 'volumes': []})
            override = (path.parent / 'override.yml').read_text()
            self.assertIn('!override', override)
            self.assertNotIn('external:', override)
            self.assertNotIn('name:', override)
            self.assertNotIn(str(Path.home() / '.config'), override)
            self.assertEqual(override.count('127.0.0.1:'), 7)
            self.assertIn('rabbitmq-data:/var/lib/rabbitmq', override)
            self.assertIn('  rabbitmq-data:', override)
            self.assertNotIn('QUEUE_MESSAGE_SIGNING_KEY', path.read_text())
            self.assertEqual((path.parent / 'qa.env').stat().st_mode & 0o777, 0o600)
            entries = dict(line.split('=', 1) for line in (path.parent / 'qa.env').read_text().splitlines())
            key_id, encoded = entries['SPEAKER_EXCERPT_KEYRING'].strip("'").split(':', 1)
            self.assertEqual(key_id, 'qa')
            self.assertEqual(len(base64.b64decode(encoded, validate=True)), 32)

    def test_create_failure_preserves_inventory_without_starting_services(self):
        with tempfile.TemporaryDirectory() as temp:
            with patch.object(self.module, 'discover', return_value={
                    'containers': [], 'networks': [], 'volumes': []}), \
                 patch.object(self.module, 'validate_config', side_effect=ValueError('unsafe config')):
                with self.assertRaises(ValueError):
                    self.module.create(Path(temp))
            paths = list(Path(temp).glob('*/inventory.json'))
            self.assertEqual(len(paths), 1)
            self.assertEqual(json.loads(paths[0].read_text())['create'], 'failed')
            self.assertEqual(json.loads(paths[0].read_text())['resourceIds'], {
                'containers': [], 'networks': [], 'volumes': []})

    def test_error_and_cancellation_always_record_and_cleanup(self):
        for error in [RuntimeError('controlled failure'), KeyboardInterrupt()]:
            with self.subTest(error=type(error).__name__), tempfile.TemporaryDirectory() as temp:
                path = Path(temp) / 'inventory.json'
                inventory = self.inventory()
                path.write_text(json.dumps(inventory))
                with patch.object(self.module, 'metrics'), \
                     patch.object(self.module, 'start', side_effect=error), \
                     patch.object(self.module, 'record_resources') as record, \
                     patch.object(self.module, 'cleanup') as cleanup:
                    with self.assertRaises(type(error)):
                        self.module.check(path)
                    record.assert_called()
                    cleanup.assert_called_once_with(path)

    def test_docker_environment_never_inherits_owner_application_settings(self):
        with patch.dict('os.environ', {'JWT_SECRET': 'owner-value', 'AUTH_DISABLED': 'true',
                                      'COMPOSE_PROJECT_NAME': 'owner-project'}):
            with patch.object(self.module, 'run', return_value='') as run:
                self.module.docker('version')
                environment = run.call_args.kwargs['env']
                for name in ['JWT_SECRET', 'AUTH_DISABLED', 'COMPOSE_PROJECT_NAME']:
                    self.assertNotIn(name, environment)

    def test_uninventoried_resource_prevents_any_deletion(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'inventory.json'
            inventory = self.inventory()
            path.write_text(json.dumps(inventory))
            labels = {'com.docker.compose.project': inventory['projectName'],
                      'sauri.validation.run': inventory['runId']}
            with patch.object(self.module, 'inspect_resource', return_value=labels), \
                 patch.object(self.module, 'discover', return_value={
                     'containers': ['owned', 'new'], 'networks': [], 'volumes': []}), \
                 patch.object(self.module, 'docker') as docker:
                with self.assertRaises(ValueError):
                    self.module.cleanup(path)
                docker.assert_not_called()

    def test_daemon_error_never_reports_cleanup_verified(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'inventory.json'
            path.write_text(json.dumps(self.inventory()))
            with patch.object(self.module, 'docker', side_effect=RuntimeError('daemon down')):
                with self.assertRaises(RuntimeError):
                    self.module.cleanup(path)
            self.assertNotEqual(json.loads(path.read_text()).get('cleanup'), 'verified')

    def test_failed_check_records_safe_stage_without_exception_secret(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'inventory.json'
            path.write_text(json.dumps(self.inventory()))
            with patch.object(self.module, 'metrics'), \
                 patch.object(self.module, 'start', side_effect=RuntimeError('private synthetic key')), \
                 patch.object(self.module, 'record_resources'), \
                 patch.object(self.module, 'cleanup'):
                with self.assertRaises(RuntimeError):
                    self.module.check(path)
            saved = json.loads(path.read_text())
            self.assertEqual(saved['validation'], {'outcome': 'failed', 'stage': 'starting'})
            self.assertNotIn('private synthetic key', path.read_text())

    def test_missing_secrets_fail_before_start_but_still_cleanup(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'inventory.json'
            path.write_text(json.dumps(self.inventory()))
            with patch.object(self.module, 'metrics'), \
                 patch.object(self.module, 'record_resources'), \
                 patch.object(self.module, 'cleanup') as cleanup:
                with self.assertRaises(FileNotFoundError):
                    self.module.check(path)
                cleanup.assert_called_once_with(path)


if __name__ == '__main__':
    unittest.main()
