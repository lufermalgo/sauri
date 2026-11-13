"""Isolated local QA lifecycle. No owner environment or global cleanup.

create writes config/inventory only. check starts the selected run and ALWAYS
cleans its resources on return, failure or interruption. An optional bounded
hold allows browser checks. cleanup can be repeated from the saved inventory.
"""
import argparse
import base64
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import secrets
import signal
import socket
import subprocess
import tempfile
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
KINDS = {'containers': 'container', 'networks': 'network', 'volumes': 'volume'}
DEFAULT_PORTS = {'portal': 15173, 'api': 18000, 'postgres': 15432,
                 's3': 19000, 'console': 19001, 'amqp': 15673, 'admin': 15674}


def run(args, env=None):
    process = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               text=True, env=env, start_new_session=True)
    try:
        stdout, _ = process.communicate()
    except BaseException:
        os.killpg(process.pid, signal.SIGTERM)
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait()
        raise
    if process.returncode:
        # Do not echo commands, environment or Docker output that may hold keys.
        raise RuntimeError(f'{args[0]} operation failed (exit {process.returncode})')
    return stdout


def docker_environment():
    # Compose interpolation must never inherit the owner's application keys or
    # project selectors. Keep only CLI connection/credential-helper essentials.
    allowed = ['PATH', 'HOME', 'TMPDIR', 'DOCKER_CONFIG', 'DOCKER_HOST',
               'DOCKER_CONTEXT', 'DOCKER_TLS_VERIFY', 'DOCKER_CERT_PATH', 'SSH_AUTH_SOCK']
    return {name: os.environ[name] for name in allowed if name in os.environ}


def docker(*args):
    return run(['docker', *args], env=docker_environment())


def save(path, inventory):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(inventory, indent=2) + '\n')
    temporary.chmod(0o600)
    temporary.replace(path)


def validate_inventory(inventory):
    if not isinstance(inventory, dict) or inventory.get('schemaVersion') != 1:
        raise ValueError('Unsupported or missing inventory')
    run_id = inventory.get('runId', '')
    if not isinstance(run_id, str) or not re.fullmatch('[a-f0-9]{12}', run_id):
        raise ValueError('Invalid run identity')
    if inventory.get('projectName') != 'sauri-local-qa-' + run_id:
        raise ValueError('Project does not match run identity')
    resources = inventory.get('resourceIds')
    if not isinstance(resources, dict) or set(resources) != set(KINDS):
        raise ValueError('Missing resource inventory')
    for ids in resources.values():
        if not isinstance(ids, list) or any(not isinstance(item, str) or not item for item in ids):
            raise ValueError('Invalid resource identity')
        if len(ids) != len(set(ids)):
            raise ValueError('Duplicate resource identity')
    return inventory


def load(path):
    return validate_inventory(json.loads(path.read_text()))


def owns(inventory, kind, identity, labels):
    try:
        validate_inventory(inventory)
    except ValueError:
        return False
    return (identity in inventory['resourceIds'].get(kind, [])
            and labels.get('com.docker.compose.project') == inventory['projectName']
            and labels.get('sauri.validation.run') == inventory['runId'])


def inspect_resource(kind, identity):
    # Inspect failure is absence ONLY after a successful exact-ID list query;
    # a disconnected daemon must never be reported as successful cleanup.
    ids = docker(KINDS[kind], 'ls', *(['-a'] if kind == 'containers' else []),
                 '-q', *(['--no-trunc'] if kind != 'volumes' else [])).split()
    if identity not in ids:
        return None
    resource = json.loads(docker(KINDS[kind], 'inspect', identity))[0]
    return ((resource.get('Config', {}).get('Labels') if kind == 'containers'
             else resource.get('Labels')) or {})


def discover(inventory):
    return {kind: docker(KINDS[kind], 'ls', *(['-a'] if kind == 'containers' else []),
                         '-q', *(['--no-trunc'] if kind != 'volumes' else []),
                         '--filter', 'label=com.docker.compose.project=' + inventory['projectName']).split()
            for kind in KINDS}


def record_resources(path):
    inventory = load(path)
    current = discover(inventory)
    for kind, ids in current.items():
        candidate = dict(inventory, resourceIds=current)
        for identity in ids:
            if not owns(candidate, kind, identity, inspect_resource(kind, identity) or {}):
                raise ValueError('Ambiguous resource ownership; cleanup requires investigation')
        inventory['resourceIds'][kind] = sorted(set(inventory['resourceIds'][kind]) | set(ids))
    save(path, inventory)


def cleanup(path):
    inventory = load(path)
    # Preflight every item before ANY deletion; never infer ownership by prefix.
    existing = []
    for kind, ids in inventory['resourceIds'].items():
        for identity in ids:
            labels = inspect_resource(kind, identity)
            if labels is not None:
                if not owns(inventory, kind, identity, labels):
                    raise ValueError('Ownership mismatch; no deletion performed')
                existing.append((kind, identity))
    unexpected = discover(inventory)
    if any(set(ids) - set(inventory['resourceIds'][kind]) for kind, ids in unexpected.items()):
        raise ValueError('Uninventoried resources; no deletion performed')
    errors = []
    for kind in KINDS:  # containers before networks and volumes
        for resource_kind, identity in existing:
            if resource_kind == kind:
                try:
                    docker(KINDS[kind], 'rm', *(['-f'] if kind == 'containers' else []), identity)
                except RuntimeError:
                    errors.append(kind)
    if errors or any(discover(inventory).values()):
        inventory['cleanup'] = 'failed'
        save(path, inventory)
        raise RuntimeError('Cleanup incomplete; inventory preserved for recovery')
    inventory['cleanup'] = 'verified'
    save(path, inventory)


def select_ports(preferred=None, attempts=100):
    preferred = preferred or DEFAULT_PORTS
    for attempt in range(attempts):
        ports = {key: port + attempt * 100 for key, port in preferred.items()}
        listeners = []
        try:
            for port in ports.values():
                listener = socket.socket()
                listeners.append(listener)
                listener.bind(('127.0.0.1', port))
            return ports
        except (OSError, OverflowError):
            pass
        finally:
            for listener in listeners:
                listener.close()
    raise RuntimeError('No free QA port block; no occupant was stopped')


def compose_args(path, inventory):
    expected = [str(ROOT / 'docker-compose.yml'), str(path.parent / 'override.yml')]
    if inventory['composeFiles'] != expected:
        raise ValueError('Unexpected Compose source files')
    return ['--env-file', str(path.parent / 'qa.env'), '-p', inventory['projectName'],
            '-f', expected[0], '-f', expected[1]]


def validate_config(path, inventory):
    config = json.loads(docker('compose', *compose_args(path, inventory), 'config', '--format', 'json'))
    project = inventory['projectName']
    for group in ['volumes', 'networks']:
        for resource in config[group].values():
            if resource.get('external') or not resource.get('name', '').startswith(project + '_'):
                raise ValueError('Configuration references resources outside this run')
    for service in config['services'].values():
        for port in service.get('ports', []):
            if port.get('host_ip') != '127.0.0.1':
                raise ValueError('Non-loopback QA publication')
        for volume in service.get('volumes', []):
            if volume['type'] == 'bind' and not Path(volume['source']).is_relative_to(path.parent):
                raise ValueError('Bind mount outside QA directory')
    return config


def create(parent):
    parent = Path(parent).resolve()
    if parent == ROOT or ROOT in parent.parents:
        raise ValueError('QA artifacts must be outside the repository')
    run_id = secrets.token_hex(6)
    directory = Path(tempfile.mkdtemp(prefix='sauri-local-qa-' + run_id + '-', dir=parent))
    directory.chmod(0o700)
    path = directory / 'inventory.json'
    ports = select_ports()
    inventory = {'schemaVersion': 1, 'runId': run_id, 'projectName': 'sauri-local-qa-' + run_id,
                 'sourceCommit': run(['git', '-C', str(ROOT), 'rev-parse', 'HEAD']).strip(),
                 'startedAt': datetime.now(timezone.utc).isoformat(),
                 'composeFiles': [str(ROOT / 'docker-compose.yml'), str(directory / 'override.yml')],
                 'resourceIds': {kind: [] for kind in KINDS}, 'ports': ports, 'checks': []}
    save(path, inventory)
    # Synthetic keys live in private files, not the public inventory/evidence.
    keyring = 'qa:' + base64.b64encode(secrets.token_bytes(32)).decode()
    values = {'AUTH_DISABLED': 'false', 'JWT_SECRET': secrets.token_hex(32),
              'QUEUE_MESSAGE_SIGNING_KEY': secrets.token_hex(32),
              'SPEAKER_EXCERPT_ACTIVE_KEY_ID': 'qa', 'SPEAKER_EXCERPT_KEYRING': keyring,
              'OBJECT_STORE_PUBLIC_ENDPOINT': f'http://localhost:{ports["s3"]}'}
    env_file = directory / 'qa.env'
    env_file.write_text(''.join(f"{key}='{value}'\n" for key, value in values.items()))
    env_file.chmod(0o600)
    home = directory / 'home' / '.config' / 'sauri'
    home.mkdir(parents=True, mode=0o700)
    for name in ['engine_token', 'recording_capability_key']:
        secret = home / name
        secret.write_text(secrets.token_hex(32) + '\n')
        secret.chmod(0o600)
    label = {'sauri.validation.run': run_id}
    bindings = {'portal': [('portal', 80)], 'api': [('api', 8000)], 'postgres': [('postgres', 5432)],
                'minio': [('s3', 9000), ('console', 9001)],
                'rabbitmq': [('amqp', 5672), ('admin', 15672)]}
    lines = ['services:']
    services = ['portal', 'api', 'worker', 'postgres', 'minio', 'rabbitmq', 'minio-volume-permissions']
    for service in services:
        lines += [f'  {service}:', '    labels: ' + json.dumps(label)]
        if service in bindings:
            lines.append('    ports: !override')
            lines.extend(f'      - "127.0.0.1:{ports[key]}:{target}"' for key, target in bindings[service])
        if service in ['api', 'worker', 'portal']:
            # Reuse image identity across runs of this source, not a tag per run.
            lines.append(f'    image: sauri-local-qa-{service}:{inventory["sourceCommit"][:12]}')
        if service == 'rabbitmq':
            # The image declares VOLUME /var/lib/rabbitmq. Name and label it
            # explicitly: an anonymous image volume cannot prove QA ownership.
            lines += ['    volumes: !override', '      - rabbitmq-data:/var/lib/rabbitmq']
        if service == 'worker':
            lines += ['    volumes: !override']
            for name in ['engine_token', 'recording_capability_key']:
                container_name = 'sauri_engine_token' if name == 'engine_token' else name
                lines.append('      - ' + json.dumps(f'{home / name}:/run/secrets/{container_name}:ro'))
    for group, names in [('networks', ['sauri-net']), ('volumes', ['pgdata', 'minio-data', 'rabbitmq-data'])]:
        lines.append(group + ':')
        for name in names:
            lines += [f'  {name}:', '    labels: ' + json.dumps(label)]
    (directory / 'override.yml').write_text('\n'.join(lines) + '\n')
    try:
        if any(discover(inventory).values()):
            raise ValueError('Run identity already exists; refusing reuse')
        validate_config(path, inventory)
    except BaseException:
        inventory['create'] = 'failed'
        save(path, inventory)
        raise
    return path


def start(path, inventory):
    # Validate secrets/config before creating any Docker resources.
    for relative in ['qa.env', 'home/.config/sauri/engine_token', 'home/.config/sauri/recording_capability_key']:
        if not (path.parent / relative).is_file():
            raise FileNotFoundError('Missing synthetic run secret')
    validate_config(path, inventory)
    docker('compose', *compose_args(path, inventory), 'build', 'api', 'worker', 'portal')
    env = docker_environment() | {'HOME': str(path.parent / 'home'),
                        'DOCKER_CONFIG': os.environ.get('DOCKER_CONFIG', str(Path.home() / '.docker')),
                        'COMPOSE_PROJECT_NAME': inventory['projectName'],
                        'COMPOSE_FILE': os.pathsep.join(inventory['composeFiles']),
                        'COMPOSE_ENV_FILES': str(path.parent / 'qa.env')}
    run(['bash', str(ROOT / '_tools/compose-bringup.sh')], env=env)


def metrics(path, phase):
    (path.parent / ('docker-space-' + phase + '.txt')).write_text(docker('system', 'df'))


def check(path, hold_seconds=0, controlled_failure=False):
    inventory = load(path)
    directory = path.parent
    stage = 'starting'
    try:
        metrics(path, 'before')
        print('QA: building and starting isolated platform', flush=True)
        start(path, inventory)
        record_resources(path)
        if controlled_failure:
            raise RuntimeError('Controlled validation failure')
        for layer, endpoint in [('portal', 'portal-health'), ('api', 'api-health')]:
            stage = layer
            url = f'http://127.0.0.1:{inventory["ports"]["portal"]}/{endpoint}'
            with urllib.request.urlopen(url, timeout=5) as response:
                if response.status != 200:
                    raise RuntimeError('HTTP check failed: ' + layer)
            evidence = directory / (layer + '.txt')
            evidence.write_text('HTTP 200; endpoint only, not dependency/inference validation\n')
            inventory = load(path)
            inventory['checks'].append({'layer': layer, 'outcome': 'passed', 'evidencePath': str(evidence)})
            save(path, inventory)
        stage = 'browser-hold'
        time.sleep(min(900, max(0, hold_seconds)))
        inventory = load(path)
        inventory['validation'] = {'outcome': 'passed', 'stage': 'http-health-only'}
        save(path, inventory)
    except BaseException:
        # Persist only a fixed stage, never the exception, command or secret.
        inventory = load(path)
        inventory['validation'] = {'outcome': 'failed', 'stage': stage}
        save(path, inventory)
        raise
    finally:
        try:
            record_resources(path)
        finally:
            cleanup(path)
            metrics(path, 'after')


def interrupt(*_):
    raise KeyboardInterrupt()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=['create', 'check', 'cleanup'])
    parser.add_argument('--inventory', type=Path)
    parser.add_argument('--directory', type=Path)
    parser.add_argument('--hold-seconds', type=int, default=0)
    parser.add_argument('--controlled-failure', action='store_true')
    args = parser.parse_args()
    signal.signal(signal.SIGTERM, interrupt)
    if args.mode == 'create':
        if not args.directory:
            parser.error('create requires an explicit external --directory')
        print(create(args.directory))
    else:
        if not args.inventory:
            parser.error('mode requires --inventory; no default project is allowed')
        path = args.inventory.resolve()
        if args.mode == 'check':
            check(path, args.hold_seconds, args.controlled_failure)
        else:
            cleanup(path)
        print(args.mode + ': completed; cleanup verified')


if __name__ == '__main__':
    main()
