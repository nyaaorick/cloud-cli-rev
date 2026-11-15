#!/usr/bin/python3
"""External GitHub updater: verify, wait for idle, restart the fixed unit, rollback."""
import datetime
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tarfile
import time
import urllib.request

REPO = 'nyaaorick/cloud-cli-rev'
BASE = Path('/srv/review/controller/cloudcli-rev-updates')
SYSTEMD = Path('/etc/systemd/system')


def atomic(path, value):
    temporary = path.with_name(path.name + '.next')
    temporary.write_text(json.dumps(value, indent=2) + '\n')
    temporary.chmod(0o600)
    temporary.replace(path)


def run(args, timeout=40, data=None):
    return subprocess.run(args, input=data, capture_output=True, check=True, timeout=timeout).stdout


def fetch(url, limit):
    if not url.startswith(('https://api.github.com/repos/' + REPO + '/',
                           'https://github.com/' + REPO + '/releases/download/')):
        raise ValueError('Untrusted release source')
    for attempt in range(3):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={
                    'User-Agent': 'cloud-cli-rev-managed-update', 'Accept': 'application/vnd.github+json'}), timeout=45) as response:
                data = response.read(limit + 1)
            if len(data) > limit:
                raise ValueError('Release download exceeds limit')
            return data
        except (OSError, TimeoutError):
            if attempt == 2:
                raise
            time.sleep(2)


def safe_extract(archive, target):
    with tarfile.open(archive, 'r:gz') as bundle:
        members = bundle.getmembers()
        if len(members) > 50000 or sum(m.size for m in members) > 1024 ** 3:
            raise ValueError('Oversized release archive')
        for item in members:
            if (not item.isfile() and not item.isdir()) or item.name.startswith('/'):
                raise ValueError('Release archive contains a link or special file')
            if '..' in Path(item.name).parts:
                raise ValueError('Release archive escapes its directory')
        bundle.extractall(str(target), members=members)


def dependency_fingerprint(lock):
    data = json.loads(lock.read_text())
    root = data['packages'][''].copy()
    root.pop('name', None)
    root.pop('version', None)
    packages = {k: v for k, v in data['packages'].items() if k}
    return hashlib.sha256(json.dumps([root, packages], sort_keys=True).encode()).hexdigest()


def runtime_permissions(release):
    # The root updater uses umask077, but the fixed app runs as cn25-manager.
    # Do not follow node_modules symlinks into the previous running dependency tree.
    for path in release.rglob('*'):
        if not path.is_symlink():
            path.chmod(0o755 if path.is_dir() or path.stat().st_mode & 0o111 else 0o644)
    release.chmod(0o755)


def health(port):
    with urllib.request.urlopen('http://127.0.0.1:%d/health' % port, timeout=5) as response:
        return json.load(response)


def process_identity(pid):
    try:
        raw = Path('/proc', str(pid), 'stat').read_text()
        fields = raw[raw.rfind(')') + 2:].split()
        return {'pid': pid, 'start': fields[19]}
    except (FileNotFoundError, ProcessLookupError):
        return None


def descendants(pid):
    # Inspect process identities only, never command lines or environments.
    parents = {}
    for entry in Path('/proc').iterdir():
        if not entry.name.isdigit():
            continue
        try:
            raw = (entry / 'stat').read_text()
            parents[int(entry.name)] = int(raw[raw.rfind(')') + 2:].split()[1])
        except (OSError, ValueError, IndexError):
            continue
    found, pending = set(), [pid]
    while pending:
        parent = pending.pop()
        children = {child for child, owner in parents.items() if owner == parent} - found
        found.update(children)
        pending.extend(children)
    return found


def authenticated_client(port, credential_file):
    # Credentials and the token remain in this process, never argv/logs/receipts.
    credential = json.loads(Path(credential_file).read_text())
    base = 'http://127.0.0.1:%d' % port
    request = urllib.request.Request(base + '/api/auth/login', method='POST',
        data=json.dumps({'username': credential['username'], 'password': credential['password']}).encode(),
        headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(request, timeout=10) as response:
        token = json.load(response)['token']
    def get(path):
        request = urllib.request.Request(base + path, headers={'Authorization': 'Bearer ' + token})
        with urllib.request.urlopen(request, timeout=10) as response:
            return json.load(response)
    return get


def idle_snapshot(config, get):
    pid = int(run(['systemctl', 'show', config['service'], '-p', 'MainPID', '--value']))
    if pid <= 1:
        raise RuntimeError('Fixed Rev service is not running')
    response = get('/api/providers/sessions/running')
    sessions = response['data']['sessions']
    if not isinstance(sessions, list):
        raise ValueError('Invalid running-session response')
    protected = sum(process_identity(item['pid']) == item for item in config.get('protectedProcesses', []))
    children = descendants(pid)
    return {'main_pid': pid, 'running_sessions': len(sessions),
            'child_processes': len(children), 'protected_processes': protected}


def wait_idle(config, save_state, get):
    until = time.monotonic() + config.get('idleWaitSeconds', 86400)
    quiet_since = None
    last_snapshot = None
    while time.monotonic() < until:
        current = idle_snapshot(config, get)
        idle = not any(current[key] for key in ('running_sessions', 'child_processes', 'protected_processes'))
        if idle:
            quiet_since = quiet_since or time.monotonic()
            if time.monotonic() - quiet_since >= config.get('quietSeconds', 30):
                return current
        else:
            quiet_since = None
        if current != last_snapshot:
            save_state(current)
            last_snapshot = current
        time.sleep(5)
    raise TimeoutError('Active turns or CLI processes still present; no restart performed')


def switch_release(config, release, previous, state, save, get):
    service = config['service']
    if service != 'cn25-console-rev.service' or config['port'] != 3302:
        raise ValueError('Unexpected fixed Rev service or port')
    dropin = SYSTEMD / (service + '.d') / '80-rev-release.conf'
    dropin.parent.mkdir(parents=True, exist_ok=True)
    before = dropin.read_bytes() if dropin.exists() else None
    expected = previous.get('dropin_sha256')
    if ((expected is None and before is not None) or
            (expected is not None and (before is None or hashlib.sha256(before).hexdigest() != expected))):
        raise RuntimeError('Release override differs from the active receipt')
    exec_start = run(['systemctl', 'show', service, '-p', 'ExecStart', '--value']).decode()
    if str(Path(previous['release']) / 'dist-server/server/index.js') not in exec_start:
        raise RuntimeError('Fixed service does not run the recorded release')
    content = ('[Service]\nExecStart=\nExecStart=' + config['node'] + ' ' +
               str(release / 'dist-server/server/index.js') + '\n').encode()
    current = Path(config['releases']).parent / 'rev-current'
    if current.exists() or current.is_symlink():
        if not current.is_symlink() or current.resolve() != Path(previous['release']).resolve():
            raise RuntimeError('Unknown Rev current link')
    prior_link = str(current.readlink()) if current.is_symlink() else None
    atomic(BASE / 'previous.json', previous)
    state.update(status='waiting-for-idle', release=str(release))
    save()
    def waiting(snapshot):
        state['idle_gate'] = snapshot
        save()
    quiet = wait_idle(config, waiting, get)
    # Recheck immediately before the switch. Any CLI/shell/provider descendant
    # blocks restarting the unit, including this updater's requesting manager.
    if idle_snapshot(config, get) != quiet:
        raise RuntimeError('Application activity changed before activation')
    state.update(status='switching', idle_gate=quiet)
    save()
    changed = False
    try:
        temporary = dropin.with_name(dropin.name + '.next')
        if temporary.exists():
            raise RuntimeError('Unrecorded service override exists')
        temporary.write_bytes(content)
        temporary.chmod(0o644)
        temporary.replace(dropin)
        changed = True
        run(['systemctl', 'daemon-reload'])
        # Fixed service, port, environment-file references and home are retained.
        run(['systemctl', 'restart', service], timeout=90)
        for _ in range(60):
            try:
                result = health(config['port'])
                if result['version'] == state['version'] and result['installMode'] == 'managed':
                    break
            except Exception:
                pass
            time.sleep(1)
        else:
            raise RuntimeError('New release failed local health check')
        for _ in range(5):
            try:
                request = urllib.request.Request(config['publicUrl'] + '/health',
                    headers={'User-Agent': 'Mozilla/5.0 CN25-Rev-Health/1.0'})
                with urllib.request.urlopen(request, timeout=15) as response:
                    result = json.load(response)
                if result['version'] == state['version'] and result['installMode'] == 'managed':
                    break
            except Exception:
                pass
            time.sleep(2)
        else:
            raise RuntimeError('New release failed fixed HTTPS health check')
        temporary = current.with_name('rev-current.next')
        if temporary.exists() or temporary.is_symlink():
            raise RuntimeError('Unrecorded activation link exists')
        temporary.symlink_to(release)
        temporary.replace(current)
        active = {'version': state['version'], 'release': str(release), 'commit': state['commit'],
                  'dropin_sha256': hashlib.sha256(content).hexdigest()}
        atomic(BASE / 'active.json', active)
        state.update(status='applied', active=active, public_url=config['publicUrl'], finished_utc=utc())
        save()
    except BaseException as error:
        state['error_type'] = type(error).__name__
        if changed:
            state['status'] = 'rolling-back'
            save()
            try:
                if dropin.read_bytes() != content:
                    raise RuntimeError('Concurrent service override prevents rollback')
                if before is None:
                    dropin.unlink()
                else:
                    dropin.write_bytes(before)
                    dropin.chmod(0o644)
                if current.is_symlink() and current.resolve() == release.resolve():
                    current.unlink()
                    if prior_link is not None:
                        current.symlink_to(prior_link)
                run(['systemctl', 'daemon-reload'])
                run(['systemctl', 'restart', service], timeout=90)
                for _ in range(60):
                    try:
                        if health(config['port'])['version'] == previous['version']:
                            break
                    except Exception:
                        pass
                    time.sleep(1)
                else:
                    raise RuntimeError('Previous release failed rollback health check')
                atomic(BASE / 'active.json', previous)
                state['status'] = 'rolled-back'
            except BaseException as rollback_error:
                state.update(status='rollback-needs-inspection', rollback_error_type=type(rollback_error).__name__)
        else:
            state['status'] = 'failed-before-switch'
        save()
        raise


def utc():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def main():
    if os.geteuid() != 0:
        raise PermissionError('Independent root update service required')
    os.umask(0o077)
    BASE.mkdir(parents=True, exist_ok=True)
    held = (BASE / 'update.lock').open('a')
    fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
    config = json.loads((BASE / 'config.json').read_text())
    if config['repository'] != REPO or not run([config['node'], '--version']).decode().startswith('v22.'):
        raise ValueError('Invalid repository or Node ABI')
    latest = json.loads(fetch('https://api.github.com/repos/' + REPO + '/releases/latest', 1024 ** 2))
    tag = latest['tag_name']
    if not re.fullmatch(r'v\d+\.\d+\.\d+-rev\.\d+', tag) or latest['draft'] or latest['prerelease']:
        raise ValueError('Invalid Rev release channel')
    active_path = BASE / 'active.json'
    previous = json.loads(active_path.read_text()) if active_path.exists() else config['initial']
    version = tag[1:]
    numbers = lambda v: tuple(map(int, re.fullmatch(r'(\d+)\.(\d+)\.(\d+)-rev\.(\d+)', v).groups()))
    if numbers(version) <= numbers(previous['version']):
        atomic(BASE / 'last-result.json', {'status': 'up-to-date', 'version': previous['version']})
        return
    attempt = BASE / tag
    if attempt.exists():
        raise RuntimeError('Prior attempt preserved; inspect durable receipts before retry')
    attempt.mkdir()
    state = {'status': 'downloading', 'version': version, 'tag': tag, 'started_utc': utc()}
    def save():
        atomic(attempt / 'deployment.json', state)
        atomic(BASE / 'last-result.json', state)
    save()
    try:
        assets = {item['name']: item['browser_download_url'] for item in latest['assets']}
        manifest_bytes = fetch(assets['release-manifest.json'], 1024 ** 2)
        manifest = json.loads(manifest_bytes)
        archive_name = 'cloud-cli-rev-' + tag + '-app.tar.gz'
        if (manifest['schemaVersion'] != 1 or manifest['repository'] != REPO or
                manifest['version'] != version or manifest['tag'] != tag or
                manifest['archive'] != archive_name or manifest['nodeMajor'] != 22 or
                not re.fullmatch('[0-9a-f]{40}', manifest['commit'])):
            raise ValueError('Release manifest identity mismatch')
        checksums = fetch(assets['SHA256SUMS'], 8192).decode()
        expected_sums = manifest['sha256'] + '  ' + archive_name + '\n' + hashlib.sha256(manifest_bytes).hexdigest() + '  release-manifest.json\n'
        if checksums != expected_sums:
            raise ValueError('Release checksum manifest mismatch')
        archive = attempt / archive_name
        archive.write_bytes(fetch(assets[archive_name], 200 * 1024 ** 2))
        if archive.stat().st_size != manifest['bytes'] or hashlib.sha256(archive.read_bytes()).hexdigest() != manifest['sha256']:
            raise ValueError('Release archive integrity check failed')
        (attempt / 'release-manifest.json').write_bytes(manifest_bytes)
        release = Path(config['releases']) / manifest['commit']
        if release.exists():
            raise RuntimeError('Existing release directory preserved')
        release.mkdir(mode=0o755)
        safe_extract(archive, release)
        package = json.loads((release / 'package.json').read_text())
        if package['version'] != version or package['name'] != 'cloud-cli-rev':
            raise ValueError('Extracted package identity mismatch')
        for filename, key in [('package-lock.json', 'lockSha256'), ('LICENSE', 'licenseSha256'), ('NOTICE', 'noticeSha256')]:
            if hashlib.sha256((release / filename).read_bytes()).hexdigest() != manifest[key]:
                raise ValueError('Release content integrity check failed')
        previous_path = Path(previous['release'])
        if dependency_fingerprint(release / 'package-lock.json') == dependency_fingerprint(previous_path / 'package-lock.json'):
            (release / 'node_modules').symlink_to((previous_path / 'node_modules').resolve())
            state['dependencies'] = 'reused matching dependency lock and Node22 ABI'
        else:
            run([config['node'], config['npmCli'], 'ci', '--omit=dev', '--prefix', str(release)], timeout=1200)
            state['dependencies'] = 'installed from release lockfile'
        runtime_permissions(release)
        marker = release / '.rev-install.json'
        marker.write_text(json.dumps({'schemaVersion': 1, 'repository': REPO, 'version': version,
                                     'updateService': 'cn25-cloudcli-rev-update.service'}) + '\n')
        marker.chmod(0o644)
        state.update(status='verified', release=str(release), commit=manifest['commit'], sha256=manifest['sha256'])
        save()
        get = authenticated_client(config['port'], config['ownerCredentialFile'])
        switch_release(config, release, previous, state, save, get)
    except BaseException as error:
        if state['status'] not in ('rolled-back', 'rollback-needs-inspection', 'failed-before-switch'):
            state['status'] = 'failed-before-switch'
        state.update(error_type=type(error).__name__, finished_utc=utc())
        save()
        raise


if __name__ == '__main__':
    try:
        main()
    except BaseException as error:
        print(json.dumps({'status': 'inspect-durable-receipt', 'error_type': type(error).__name__}))
        sys.exit(1)
