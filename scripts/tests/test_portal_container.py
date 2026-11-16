"""Real Docker tests for the static portal and proxy, not backend integration.

Uses a labelled, isolated network, a disposable builder/cache and a synthetic
HTTP API double. Always removes owned containers, network, images and builder.
Requires Docker; missing infrastructure fails rather than silently skipping.
"""
import base64
import hashlib
import http.client
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import subprocess
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[2]
MARKER = "SAURI_PRIVATE_CONTEXT_SENTINEL_3e5ea103"


def docker(*args, check=True):
    return subprocess.run(['docker', *args], check=check, capture_output=True, text=True)


class PortalContainerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.run_id = secrets.token_hex(6)
        cls.label = 'sauri.portal-test.run=' + cls.run_id
        cls.network = 'sauri-portal-qa-' + cls.run_id
        cls.builder = cls.network + '-builder'
        cls.builder_created = False
        cls.image = cls.network + ':portal'
        cls.audit_image = cls.network + ':context'
        cls.api_image = cls.network + ':api-double'
        cls.api = cls.network + '-api'
        cls.portal = cls.network + '-portal'
        cls.addClassCleanup(cls.cleanup)
        cls.temp = tempfile.TemporaryDirectory(prefix=cls.network + '-')
        cls.addClassCleanup(cls.temp.cleanup)
        context = Path(cls.temp.name)
        # Copy only known source/manifests; seed excluded paths to test the actual
        # Docker context filter without reading any owner's private files.
        required = ['package.json', 'package-lock.json', 'extension/package.json',
                    'frontend', 'packages/shared-types', '.dockerignore',
                    'scripts/platform/inline-script-hash.mjs']
        for relative in required:
            source = ROOT / relative
            target = context / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            if source.is_dir():
                shutil.copytree(source, target, ignore=shutil.ignore_patterns(
                    'node_modules', 'dist', '.env*', '__pycache__'))
            else:
                shutil.copy2(source, target)
        for relative in ['.env.private', '.git/private', '.worktrees/private',
                         '.claude/private', 'backend/private', 'node_modules/private',
                         'frontend/.env.local', 'frontend/src/.env.private',
                         'frontend/src/private.wav', 'frontend/dist/private',
                         'packages/shared-types/node_modules/private']:
            path = context / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(MARKER)
        (context / 'audit.Dockerfile').write_text(
            'FROM scratch\nCOPY . /context/\n')
        docker('info')
        docker('buildx', 'create', '--name', cls.builder, '--driver', 'docker-container')
        cls.builder_created = True
        for image, file in [(cls.audit_image, 'audit.Dockerfile'),
                            (cls.image, 'frontend/Dockerfile')]:
            result = docker('buildx', 'build', '--builder', cls.builder, '--load',
                            '--label', cls.label, '-t', image, '-f', str(context / file),
                            str(context), check=False)
            if result.returncode:
                raise AssertionError('Docker build failed:\n' + result.stderr[-12000:])
        docker('network', 'create', '--label', cls.label, cls.network)
        # Reuse the build stage for the explicit API double. Its loaded image
        # belongs to this run and is removed along with the disposable cache.
        docker('buildx', 'build', '--builder', cls.builder, '--load',
               '--target', 'build', '--label', cls.label, '-t', cls.api_image,
               '-f', str(context / 'frontend/Dockerfile'), str(context))
        script = """const http=require('http');http.createServer((req,res)=>{
          const code=req.url.startsWith('/api/status/')?Number(req.url.split('/')[3].split('?')[0]):200;
          if(req.method==='POST'){let parts=[];req.on('data',p=>parts.push(p));req.on('end',()=>{res.writeHead(201,{'Content-Type':'application/octet-stream'});res.end(Buffer.concat(parts))});return;}
          res.writeHead(code,{'Content-Type':'application/json'});
          res.end(JSON.stringify({path:req.url,authorization:req.headers.authorization||null,method:req.method}));
        }).listen(8000,'0.0.0.0');"""
        docker('run', '-d', '--name', cls.api, '--label', cls.label,
               '--network', cls.network, '--network-alias', 'api', cls.api_image, 'node', '-e', script)
        docker('run', '-d', '--name', cls.portal, '--label', cls.label,
               '--network', cls.network, '-p', '127.0.0.1::80', cls.image)
        info = json.loads(docker('inspect', cls.portal).stdout)[0]
        cls.port = int(info['NetworkSettings']['Ports']['80/tcp'][0]['HostPort'])
        for _ in range(100):
            try:
                if cls.request('/api-health')[0] == 200:
                    break
            except (OSError, http.client.HTTPException):
                pass
            time.sleep(.2)
        else:
            raise AssertionError('Portal/proxy did not become available')
        print(f'PORTAL_TEST_URL=http://127.0.0.1:{cls.port}', flush=True)

    @classmethod
    def cleanup(cls):
        errors = []
        for name in [cls.portal, cls.api]:
            result = docker('inspect', name, check=False)
            if result.returncode == 0:
                labels = json.loads(result.stdout)[0]['Config']['Labels'] or {}
                if labels.get('sauri.portal-test.run') != cls.run_id:
                    errors.append('Refusing foreign container: ' + name)
                    continue
                docker('rm', '-f', name)
        result = docker('network', 'inspect', cls.network, check=False)
        if result.returncode == 0:
            if json.loads(result.stdout)[0]['Labels'].get('sauri.portal-test.run') == cls.run_id:
                docker('network', 'rm', cls.network)
            else:
                errors.append('Refusing foreign network')
        for image in [cls.image, cls.audit_image, cls.api_image]:
            result = docker('image', 'inspect', image, check=False)
            if result.returncode == 0:
                if (json.loads(result.stdout)[0]['Config']['Labels'] or {}).get('sauri.portal-test.run') == cls.run_id:
                    docker('image', 'rm', image)
                else:
                    errors.append('Refusing foreign image')
        # Builder name is an unpredictable per-execution ID, never a shared one.
        if cls.builder_created:
            docker('buildx', 'rm', cls.builder)
        for kind in ['container', 'network', 'image']:
            result = docker(kind, 'ls', '-q', '--filter', 'label=' + cls.label)
            if result.stdout.strip():
                errors.append('Residual resources: ' + kind + ' ' + result.stdout)
        if errors:
            raise AssertionError('; '.join(errors))
        print('PORTAL_TEST_CLEANUP=verified', flush=True)

    @classmethod
    def tearDownClass(cls):
        # Optional bounded window for a real browser check before automatic cleanup.
        time.sleep(min(300, max(0, int(os.environ.get('PORTAL_TEST_HOLD_SECONDS', '0')))))

    @classmethod
    def request(cls, path, method='GET', body=None, headers=None):
        connection = http.client.HTTPConnection('127.0.0.1', cls.port, timeout=10)
        try:
            connection.request(method, path, body=body, headers=headers or {})
            response = connection.getresponse()
            return response.status, dict(response.getheaders()), response.read()
        finally:
            connection.close()

    def test_static_spa_and_assets(self):
        code, headers, index = self.request('/')
        self.assertEqual(code, 200)
        self.assertIn('text/html', headers['Content-Type'])
        self.assertIn('no-cache', headers.get('Cache-Control', ''))
        self.assertEqual(self.request('/meetings/synthetic')[2], index)
        assets = re.findall(rb'(?:src|href)="(/assets/[^\"]+)"', index)
        self.assertTrue(assets)
        for asset in assets:
            code, headers, content = self.request(asset.decode())
            self.assertEqual(code, 200)
            self.assertNotIn('text/html', headers['Content-Type'])
            self.assertNotIn(MARKER.encode(), content)
            self.assertNotIn(b'http://api:8000', content)
        self.assertEqual(self.request('/assets/missing.js')[0], 404)

    def test_health_and_proxy_contract(self):
        self.assertEqual(self.request('/portal-health')[2], b'ok\n')
        code, _, body = self.request('/api-health')
        self.assertEqual(code, 200)
        self.assertEqual(json.loads(body)['path'], '/health')
        for status in [200, 401, 403, 404, 422, 500]:
            path = f'/api/status/{status}?encoded=a%2Fb&x=2'
            code, headers, body = self.request(path, headers={'Authorization': 'Bearer synthetic-only'})
            self.assertEqual(code, status)
            self.assertIn('application/json', headers['Content-Type'])
            self.assertEqual(json.loads(body), {'path': path, 'authorization': 'Bearer synthetic-only', 'method': 'GET'})
        content = b'x' * (2 * 1024 * 1024)
        self.assertEqual(self.request('/api/upload', 'POST', content)[::2], (201, content))

    def test_security_headers_and_csp(self):
        required = {'X-Content-Type-Options': 'nosniff', 'X-Frame-Options': 'DENY',
                    'Referrer-Policy': 'no-referrer'}
        for path in ['/', '/index.html', '/assets/missing.js', '/portal-health', '/meetings/synthetic']:
            _, headers, _ = self.request(path)
            for name, value in required.items():
                self.assertEqual(headers.get(name), value, (path, name))
            self.assertIn('camera=()', headers.get('Permissions-Policy', ''), path)
            self.assertIn("frame-ancestors 'none'", headers.get('Content-Security-Policy', ''), path)
            self.assertNotIn('Strict-Transport-Security', headers, path)
            self.assertEqual(headers.get('Server'), 'nginx', path)
        csp = self.request('/')[1]['Content-Security-Policy']
        self.assertIn("default-src 'self'", csp)
        self.assertNotIn("'unsafe-inline'", csp)
        self.assertNotIn('*', csp)
        self.assertIn('http://localhost:9000', csp)  # default object-store origin for signed media
        # The single inline script (theme bootstrap) is allowed by its exact hash.
        index = self.request('/')[2].decode()
        inline = re.findall(r'<script(?![^>]*\bsrc=)[^>]*>([\s\S]*?)</script>', index)
        self.assertEqual(len(inline), 1)
        digest = base64.b64encode(hashlib.sha256(inline[0].encode()).digest()).decode()
        self.assertIn(f"'sha256-{digest}'", csp)
        # HSTS only when the request arrived over HTTPS (proxy header), never over plain HTTP.
        https = self.request('/', headers={'X-Forwarded-Proto': 'https'})[1]
        self.assertIn('max-age=', https.get('Strict-Transport-Security', ''))
        # Proxied API responses keep the API's own headers and are not given the portal CSP.
        _, api_headers, _ = self.request('/api/status/200')
        self.assertNotIn('Content-Security-Policy', api_headers)

    def test_nginx_and_runtime_context(self):
        docker('exec', self.portal, 'nginx', '-t')
        config = docker('exec', self.portal, 'nginx', '-T').stdout
        for directive in ['client_max_body_size 4g;', 'server_tokens off;', 'proxy_request_buffering off;',
                          'proxy_connect_timeout 5s;', 'proxy_read_timeout 3600s;',
                          'proxy_send_timeout 3600s;', 'proxy_http_version 1.1;',
                          'proxy_cache off;', 'autoindex off;']:
            self.assertIn(directive, config)
        listing = docker('exec', self.portal, 'find', '/usr/share/nginx/html', '-type', 'f').stdout
        self.assertNotRegex(listing, r'(?m)(node_modules|\.env|\.tsx?$|\.map$|package-lock|private)')
        # Export scratch audit image via an owned stopped container, then inspect
        # names/content without ever executing anything from the build context.
        audit = self.network + '-audit'
        docker('create', '--name', audit, '--label', self.label, self.audit_image, '/unused')
        try:
            docker('cp', audit + ':/context', str(Path(self.temp.name) / 'exported'))
            exported = Path(self.temp.name) / 'exported'
            for path in exported.rglob('*'):
                if path.is_file():
                    self.assertNotIn(MARKER.encode(), path.read_bytes(), str(path))
            self.assertFalse((exported / 'backend').exists())
        finally:
            docker('rm', audit)

    def test_z_api_failure_is_not_spa_success(self):
        docker('stop', self.api)
        try:
            self.assertIn(self.request('/api/v1/meetings')[0], [502, 504])
            self.assertIn(self.request('/api-health')[0], [502, 504])
            self.assertEqual(self.request('/portal-health')[0], 200)
        finally:
            docker('start', self.api)


if __name__ == '__main__':
    unittest.main()
