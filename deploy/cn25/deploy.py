#!/usr/bin/python3
"""Root deployment supervisor. Never stops manager/review units or alters their homes."""
import datetime
import hashlib
import json
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request

BASE = Path('/srv/review/controller/cloudcli-first-20261115')
SOURCE = Path('/srv/review/cloudcli/source')
ROOT = SOURCE.parent
SSH = ['/usr/bin/ssh', '-F', '/srv/review/secrets/manager-access/ssh_config', '-o', 'ConnectTimeout=15', '-o', 'ServerAliveInterval=15', '-o', 'ServerAliveCountMax=3', 'console-vps']
URL = 'https://cn25.foliodude.it.com:8443'


def run(args, **kwargs):
    return subprocess.run(args, check=True, **kwargs)


def receipt(name, value):
    p = BASE / name
    p.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')
    p.chmod(0o600)


def tree_digest(directory):
    digest = hashlib.sha256()
    for p in sorted(directory.rglob('*')):
        if p.is_file():
            digest.update(str(p.relative_to(directory)).encode() + b'\0')
            digest.update(hashlib.sha256(p.read_bytes()).digest())
    return digest.hexdigest()


def http(path, body=None, token=None, method=None):
    headers = {'Content-Type': 'application/json'}
    if token:
        headers['Authorization'] = 'Bearer ' + token
    request = urllib.request.Request('http://127.0.0.1:3301' + path, data=json.dumps(body).encode() if body is not None else None, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=90) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        raise RuntimeError('Private HTTP operation failed with status ' + str(error.code)) from None


def main():
    os.umask(0o077)
    ops = SOURCE / 'deploy/cn25'
    sha = subprocess.check_output(['git', '-C', str(SOURCE), 'rev-parse', 'HEAD'], text=True).strip()
    assert not subprocess.check_output(['git', '-C', str(SOURCE), 'status', '--porcelain', '--untracked-files=no']), 'Tracked source must be clean'
    approval = json.loads((BASE / 'review-approved.json').read_text())
    assert approval['sha'] == sha and approval['approved'] is True, 'Independent final SHA review is required'
    tests = json.loads((BASE / 'tests-approved.json').read_text())
    assert tests['sha'] == sha and tests['passed'] is True, 'Final source checks are required'
    assert tests['lockfile_sha256'] == hashlib.sha256((SOURCE / 'package-lock.json').read_bytes()).hexdigest()
    assert tests['build_parameters'] == {'node': 'v22.23.4', 'VITE_CN25_MANAGER_MODE': '1'}
    assert tests['dependency_sha256'] == tree_digest(SOURCE / 'node_modules'), 'Tested dependency tree changed before packaging'
    for name in ['dist', 'dist-server']:
        assert tests['compiled_sha256'][name] == tree_digest(SOURCE / name), 'Tested build changed before packaging'
    receipt('progress.json', {'phase': 'artifact', 'source_sha': sha, 'updated_at': datetime.datetime.now(datetime.timezone.utc).isoformat()})
    release = ROOT / 'releases' / sha
    assert not release.exists(), 'Release path already exists; inspect prior result before retry'
    release.parent.mkdir(mode=0o755, exist_ok=True)
    release.parent.chmod(0o755)
    release.mkdir(mode=0o755)
    archive = subprocess.Popen(['git', '-C', str(SOURCE), 'archive', sha], stdout=subprocess.PIPE)
    run(['tar', '-x', '-C', str(release)], stdin=archive.stdout)
    archive.stdout.close()
    assert archive.wait() == 0
    for name in ['dist', 'dist-server', 'node_modules']:
        shutil.copytree(SOURCE / name, release / name, symlinks=True)
    for name in ['dist', 'dist-server']:
        assert tests['compiled_sha256'][name] == tree_digest(release / name), 'Packaged build differs from tested build'
    assert tests['dependency_sha256'] == tree_digest(release / 'node_modules')
    # Root owns the deployable code; console state lives exclusively in the manager home.
    for root, dirs, files in os.walk(release):
        os.chown(root, 0, 0)
        os.chmod(root, 0o755)
        for name in files:
            p = Path(root) / name
            if p.is_symlink():
                os.lchown(p, 0, 0)
            else:
                mode = p.stat().st_mode
                os.chown(p, 0, 0)
                os.chmod(p, 0o755 if mode & 0o111 else 0o644)
    artifact = ROOT / ('cloudcli-' + sha + '.tar.gz')
    run(['tar', '--sort=name', '--mtime=@0', '--owner=0', '--group=0', '--numeric-owner', '-czf', str(artifact), '-C', str(release), '.'])
    digest = hashlib.sha256()
    with artifact.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    receipt('artifact.json', {'source_sha': sha, 'upstream': '2053f3d7a086fd44f7fe373c913da487629b0a95', 'version': '1.37.8', 'artifact': str(artifact), 'sha256': digest.hexdigest(), 'release': str(release)})
    run(['sudo', '-n', '-u', 'cn25-manager', 'test', '-r', str(release / 'dist-server/server/index.js')])
    current = ROOT / 'current'
    previous = str(current.resolve()) if current.exists() else None
    assert not previous, 'Existing deployment requires an explicit recorded update path'
    for unit in ['cn25-console.service', 'cn25-console-tunnel.service']:
        assert not Path('/etc/systemd/system', unit).exists(), 'Unowned console unit was preserved'
    receipt('rollback.json', {'previous_release': previous, 'stop_only': ['cn25-console.service', 'cn25-console-tunnel.service'], 'remove_vhost': '/etc/nginx/conf.d/cn25-console.conf', 'retain': ['owner credentials', 'auth.db', 'all native history', 'manager launcher/home/fixed CLI', 'controller and eight workers', 'DNS/TLS recovery material'], 'source_sha': sha})
    current.symlink_to(release)
    for unit in ['cn25-console.service', 'cn25-console-tunnel.service']:
        shutil.copyfile(ops / unit, Path('/etc/systemd/system') / unit)
        os.chmod(Path('/etc/systemd/system') / unit, 0o644)
    run(['systemd-analyze', 'verify', '/etc/systemd/system/cn25-console.service', '/etc/systemd/system/cn25-console-tunnel.service'])
    run(['systemctl', 'daemon-reload'])
    run(['systemctl', 'enable', '--now', 'cn25-console.service'])
    for attempt in range(60):
        try:
            if http('/health')['status'] == 'ok':
                break
        except Exception:
            time.sleep(1)
    else:
        raise RuntimeError('Console failed to become healthy; preserved for diagnosis')
    owner_path = Path('/srv/review/secrets/console-owner.json')
    status = http('/api/auth/status')
    if not owner_path.exists():
        assert status['needsSetup'] is True, 'Existing owner must be preserved'
        fd = os.open(owner_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, 'w') as stream:
            json.dump({'username': 'cn25-owner', 'password': secrets.token_urlsafe(36)}, stream)
            stream.write('\n')
    assert owner_path.stat().st_uid == 0 and owner_path.stat().st_mode & 0o777 == 0o600
    owner = json.loads(owner_path.read_text())
    auth = http('/api/auth/register' if status['needsSetup'] else '/api/auth/login', owner)
    token = auth['token']
    http('/api/user/preferences', {'selectedProvider': 'codex'}, token, 'PATCH')
    http('/api/user/complete-onboarding', {}, token)
    assert http('/api/auth/status')['needsSetup'] is False
    ready = http('/api/providers/codex/auth/status', token=token)
    assert ready['data']['authenticated'] is True and ready['data']['method'] == 'custom_provider', 'Real native BF readiness failed'
    receipt('local-acceptance.json', {'owner_preprovisioned': True, 'owner_path': str(owner_path), 'bf_native_ready': True, 'provider_method': ready['data']['method'], 'native_version': ready['data']['installedVersion']})
    run(['systemctl', 'enable', '--now', 'cn25-console-tunnel.service'])
    for attempt in range(12):
        try:
            run(SSH + ['python3 -c \'import urllib.request,json; assert json.load(urllib.request.urlopen("http://127.0.0.1:13301/api/auth/status",timeout=10))["needsSetup"] is False\''], timeout=30)
            break
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
            time.sleep(5)
    else:
        raise RuntimeError('Reverse tunnel not confirmed; public vhost was not installed')
    for local, remote in [('nginx.conf', 'nginx.conf'), ('vps-publish.py', 'publish.py')]:
        run(SSH + ['umask 077; cat > /etc/cn25-console/' + remote], input=(ops / local).read_bytes(), timeout=45)
    receipt('progress.json', {'phase': 'public-switch-started', 'source_sha': sha, 'url': URL})
    run(SSH + ['systemd-run --unit=cn25-console-publish-20261115 --wait /usr/bin/python3 /etc/cn25-console/publish.py'], timeout=120)
    receipt('deployed.json', {'url': URL, 'source_sha': sha, 'at': datetime.datetime.now(datetime.timezone.utc).isoformat(), 'browser_acceptance': 'pending', 'owner_path': str(owner_path)})
    print('CloudCLI deployed; browser acceptance remains mandatory')


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        receipt('deployment-error.json', {'error_type': type(error).__name__, 'message': str(error), 'action': 'Preserved all state. Inspect exact phase before retry; do not replay unknown results.'})
        raise
