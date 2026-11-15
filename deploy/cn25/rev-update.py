#!/usr/bin/python3
"""GitHub-only immutable releases; never replace or stop an existing manager unit."""
import datetime
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess
import sys
import tarfile
import time
import urllib.request

REPO = 'nyaaorick/cloud-cli-rev'
BASE = Path('/srv/review/controller/cloudcli-rev-updates')


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


def health(port):
    with urllib.request.urlopen('http://127.0.0.1:%d/health' % port, timeout=5) as response:
        return json.load(response)


def remote(ssh, code):
    # Each remote mutation is executed by its own persistent systemd unit.
    return json.loads(run(ssh + ['python3 -'], timeout=100, data=code.encode()))


def remote_job(ssh, tag, action, body):
    directory = '/etc/cn25-console/rev-updates/' + tag
    unit = 'cn25-rev-' + tag + '-' + action
    script = directory + '/' + action + '.py'
    receipt = directory + '/' + action + '.json'
    payload = ('import json,pathlib,subprocess,os\nos.umask(0o077)\n'
               'base=pathlib.Path(%r);base.mkdir(parents=True,exist_ok=True)\n'
               'p=pathlib.Path(%r);r=pathlib.Path(%r)\n'
               'assert not p.exists() and not r.exists(), "Prior remote operation needs readback"\n'
               'p.write_text(%r)\n'
               'subprocess.run(["systemd-run","--quiet","--wait","--collect","--unit",%r,'
               '"--property=StandardOutput=null","--property=StandardError=null","/usr/bin/python3",str(p)],'
               'check=True,capture_output=True,timeout=70)\nprint(r.read_text())\n'
               % (directory, script, receipt,
                  body + '\npathlib.Path(%r).write_text(json.dumps(result)+"\\n")\n' % receipt, unit))
    return remote(ssh, payload)


def main():
    if os.geteuid() != 0:
        raise PermissionError('Independent root deployment service required')
    os.umask(0o077)
    BASE.mkdir(parents=True, exist_ok=True)
    held = (BASE / 'update.lock').open('a')
    fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
    config = json.loads((BASE / 'config.json').read_text())
    if config['repository'] != REPO:
        raise ValueError('Wrong Rev repository')
    if not run([config['node'], '--version']).decode().startswith('v22.'):
        raise ValueError('Managed Rev updates require the configured Node22 ABI')
    latest = json.loads(fetch('https://api.github.com/repos/' + REPO + '/releases/latest', 1024 ** 2))
    tag = latest['tag_name']
    if not re.fullmatch(r'v\d+\.\d+\.\d+-rev\.\d+', tag) or latest['draft'] or latest['prerelease']:
        raise ValueError('Invalid Rev release channel')
    active_path = BASE / 'active.json'
    active = json.loads(active_path.read_text()) if active_path.exists() else config['initial']
    current_link = Path(config['releases']).parent / 'rev-current'
    launcher = Path('/usr/local/bin/cloud-cli-rev')
    launcher_text = '#!/bin/sh\nexec ' + config['node'] + ' ' + str(current_link / 'dist-server/server/modules/cli/cli.js') + ' "$@"\n'
    if launcher.exists() and launcher.read_text() != launcher_text:
        raise RuntimeError('Existing Rev launcher belongs to another installation')
    if current_link.is_symlink() and current_link.resolve() != Path(active['release']).resolve():
        raise RuntimeError('Existing Rev current link differs from the active receipt')
    if current_link.exists() and not current_link.is_symlink():
        raise RuntimeError('Rev current path is not an owned symlink')
    version = tag[1:]
    if version == active['version']:
        atomic(BASE / 'last-result.json', {'status': 'up-to-date', 'version': version})
        return
    # The published channel is monotonic; stale latest metadata cannot downgrade a host.
    numbers = lambda value: tuple(map(int, re.fullmatch(r'(\d+)\.(\d+)\.(\d+)-rev\.(\d+)', value).groups()))
    if numbers(version) <= numbers(active['version']):
        raise ValueError('Refusing a Rev downgrade')
    attempt = BASE / tag
    if attempt.exists():
        raise RuntimeError('Prior deployment exists; inspect its durable receipts before retrying')
    attempt.mkdir()
    state = {'status': 'downloading', 'version': version, 'tag': tag,
             'started_utc': datetime.datetime.now(datetime.timezone.utc).isoformat()}
    def save():
        atomic(attempt / 'deployment.json', state)
        atomic(BASE / 'last-result.json', state)
    save()
    try:
        assets = {item['name']: item['browser_download_url'] for item in latest['assets']}
        manifest = json.loads(fetch(assets['release-manifest.json'], 1024 ** 2))
        archive_name = 'cloud-cli-rev-' + tag + '-app.tar.gz'
        if (manifest['schemaVersion'] != 1 or manifest['repository'] != REPO
                or manifest['version'] != version or manifest['tag'] != tag
                or manifest['archive'] != archive_name or manifest['nodeMajor'] != 22
                or not re.fullmatch('[0-9a-f]{40}', manifest['commit'])):
            raise ValueError('Release manifest identity mismatch')
        archive = attempt / archive_name
        archive.write_bytes(fetch(assets[archive_name], 200 * 1024 ** 2))
        if (archive.stat().st_size != manifest['bytes'] or
                hashlib.sha256(archive.read_bytes()).hexdigest() != manifest['sha256']):
            raise ValueError('Release archive integrity check failed')
        release = Path(config['releases']) / manifest['commit']
        if release.exists():
            raise RuntimeError('Existing release directory preserved')
        release.mkdir(mode=0o755)
        safe_extract(archive, release)
        package = json.loads((release / 'package.json').read_text())
        if package['version'] != version or package['name'] != 'cloud-cli-rev':
            raise ValueError('Extracted package identity mismatch')
        controller_source = (release / 'deploy/cn25/rev-update.py').read_text()
        compile(controller_source, '<next-rev-controller>', 'exec')
        if hashlib.sha256((release / 'package-lock.json').read_bytes()).hexdigest() != manifest['lockSha256']:
            raise ValueError('Dependency lock integrity check failed')
        previous = Path(active['release'])
        if dependency_fingerprint(release / 'package-lock.json') == dependency_fingerprint(previous / 'package-lock.json'):
            (release / 'node_modules').symlink_to((previous / 'node_modules').resolve())
            state['dependencies'] = 'reused immutable matching lock/Node ABI'
        else:
            run([config['node'], config['npmCli'], 'ci', '--omit=dev', '--prefix', str(release)], timeout=900)
            state['dependencies'] = 'installed from release lockfile'
        for path in release.rglob('*'):
            if not path.is_symlink():
                path.chmod(0o755 if path.is_dir() or path.stat().st_mode & 0o111 else 0o644)
        marker = release / '.rev-install.json'
        marker.write_text(json.dumps({'schemaVersion': 1, 'repository': REPO, 'version': version,
                                     'updateService': 'cn25-cloudcli-rev-update.service'}) + '\n')
        marker.chmod(0o644)
        port, forward_port = active['port'] + 1, active['forward_port'] + 1
        if not 3303 <= port < 3400 or not 13303 <= forward_port < 13400:
            raise ValueError('Managed port allocation exhausted')
        with socket.socket() as test:
            test.bind(('127.0.0.1', port))
        ssh = ['/usr/bin/ssh', '-T', '-F', config['sshConfig'], '-o', 'BatchMode=yes',
               '-o', 'ControlMaster=no', '-o', 'ControlPath=none', '-o', 'ConnectTimeout=15', 'console-vps']
        # Separate guard scope: the existing production pair and owner are never touched.
        wrapper_path = '/etc/cn25-console/rev-updates/' + tag + '/lease.py'
        wrapper = ("import importlib.util,pathlib,sys\n"
                   "s=importlib.util.spec_from_file_location('lease','/etc/cn25-console/forward-lease.py')\n"
                   "m=importlib.util.module_from_spec(s);s.loader.exec_module(m)\n"
                   "m.BASE=pathlib.Path(%r);m.PORTS={%d}\nsys.exit(m.main())\n"
                   % ('/etc/cn25-console/rev-updates/' + tag + '/lease', forward_port))
        state.update(status='needs-remote-readback', phase='stage', release=str(release), port=port, forward_port=forward_port)
        save()
        stage_body = '''import pathlib,json,re,subprocess,hashlib,fcntl
base=pathlib.Path('/etc/cn25-console');lock=(base/'primary-ingress.lock').open('a');fcntl.flock(lock,fcntl.LOCK_EX)
primary=pathlib.Path('/etc/nginx/conf.d/cn25-console.conf');content=primary.read_bytes()
assert hashlib.sha256(content).hexdigest()==EXPECTED
assert all(not x.split()[3].endswith(':%d'%FORWARD) for x in subprocess.check_output(['ss','-Hlnpt'],text=True).splitlines())
candidate=pathlib.Path('/etc/nginx/conf.d/cn25-console-rev-updates.conf')
if candidate.exists():assert hashlib.sha256(candidate.read_bytes()).hexdigest()==CANDIDATE
else:
 assert not any(re.search(r'listen\\s+(?:\\[::\\]:|\\S+:)?2053\\b',p.read_text()) for p in pathlib.Path('/etc/nginx/conf.d').glob('*.conf'))
wrapper=pathlib.Path(WRAPPER_PATH);assert not wrapper.exists();wrapper.write_text(WRAPPER);wrapper.chmod(0o600)
old=candidate.read_bytes() if candidate.exists() else None
planned=content.replace(b'listen 8443 ssl;',b'listen 2053 ssl;').replace(('127.0.0.1:%d'%OLD_FORWARD).encode(),('127.0.0.1:%d'%FORWARD).encode())
assert planned!=content and b'listen 2053 ssl;' in planned
candidate.write_bytes(planned)
try:
 subprocess.run(['nginx','-t'],check=True,capture_output=True);subprocess.run(['systemctl','reload','nginx'],check=True,capture_output=True)
except BaseException:
 if old is None:candidate.unlink()
 else:candidate.write_bytes(old)
 raise
result={'status':'staged','primary_sha256':hashlib.sha256(content).hexdigest(),'candidate_sha256':hashlib.sha256(planned).hexdigest()}
'''
        parameters = {'EXPECTED': active['primary_sha256'], 'CANDIDATE': active.get('candidate_sha256'),
                      'FORWARD': forward_port, 'OLD_FORWARD': active['forward_port'],
                      'WRAPPER_PATH': wrapper_path, 'WRAPPER': wrapper}
        stage_body = '\n'.join(k + '=' + repr(v) for k, v in parameters.items()) + '\n' + stage_body
        staged = remote_job(ssh, tag, 'stage', stage_body)
        state['remote_stage'] = staged
        state['status'] = 'staged'
        save()
        client = (release / 'deploy/cn25/forward-client.py').read_text()
        client = client.replace('/srv/review/controller/cloudcli-forward-20261115', str(attempt / 'forward'))
        client = client.replace("REMOTE='/etc/cn25-console/forward-lease.py'", 'REMOTE=' + repr(wrapper_path))
        pair = "'-R','127.0.0.1:13301:127.0.0.1:3301','-R','127.0.0.1:13302:127.0.0.1:3302'"
        if client.count(pair) != 1:
            raise ValueError('Unexpected forward client template')
        client = client.replace(pair, "'-R','127.0.0.1:%d:127.0.0.1:%d'" % (forward_port, port))
        client = client.replace("'ports':[13301,13302]", "'ports':[%d]" % forward_port)
        (attempt / 'forward-client.py').write_text(client)
        unit_name = 'cn25-console-rev-' + tag + '.service'
        tunnel_name = 'cn25-console-rev-' + tag + '-forward.service'
        app_unit = Path(config['baseServiceFile']).read_text()
        app_unit, changed_port = re.subn(r'^Environment=SERVER_PORT=\d+$', 'Environment=SERVER_PORT=%d' % port, app_unit, flags=re.M)
        app_unit, changed_entry = re.subn(r'^ExecStart=.+$', 'ExecStart=' + config['node'] + ' ' + str(release / 'dist-server/server/index.js'), app_unit, flags=re.M)
        if changed_port != 1 or changed_entry != 1:
            raise ValueError('Unexpected application service template')
        app_unit = re.sub(r'^Standard(?:Output|Error)=.+$', lambda m: m.group().split('=')[0] + '=null', app_unit, flags=re.M)
        unit_path = Path('/etc/systemd/system') / unit_name
        tunnel_path = Path('/etc/systemd/system') / tunnel_name
        if unit_path.exists() or tunnel_path.exists():
            raise RuntimeError('Existing service units preserved')
        unit_path.write_text(app_unit)
        tunnel_path.write_text('''[Unit]
Description=Independent leased forward for Cloud Cli rev release
Requires=cn25-infra-direct-route.service
Wants=network-online.target
After=network-online.target cn25-infra-direct-route.service
[Service]
Type=exec
User=root
UMask=0077
ExecStart=/usr/bin/python3 CLIENT
Restart=on-failure
RestartSec=50
TimeoutStopSec=10
KillMode=mixed
StandardOutput=null
StandardError=null
[Install]
WantedBy=multi-user.target
'''.replace('CLIENT', str(attempt / 'forward-client.py')))
        unit_path.chmod(0o644)
        tunnel_path.chmod(0o644)
        run(['systemd-analyze', 'verify', str(unit_path), str(tunnel_path)])
        run(['systemctl', 'daemon-reload'])
        run(['systemctl', 'enable', '--now', unit_name])
        for _ in range(60):
            try:
                if health(port)['version'] == version:
                    break
            except Exception:
                pass
            time.sleep(1)
        else:
            raise RuntimeError('New independent application failed health check')
        run(['systemctl', 'enable', '--now', tunnel_name])
        for _ in range(140):
            status_path = attempt / 'forward/status.json'
            if status_path.exists():
                forward = json.loads(status_path.read_text())
                if forward.get('state') == 'active' and time.time() - forward['at'] < 20:
                    break
            time.sleep(1)
        else:
            raise RuntimeError('New independent forward failed health check')
        url = 'https://' + config['hostname'] + ':2053'
        for _ in range(3):
            try:
                with urllib.request.urlopen(url + '/health', timeout=20) as response:
                    public = json.load(response)
                if public['version'] == version and public['installMode'] == 'managed':
                    break
            except Exception:
                pass
        else:
            raise RuntimeError('Public candidate did not serve the managed Rev version')
        # Save mutation intent first; a lost SSH result is not blindly replayed.
        state.update(status='needs-remote-readback', phase='promote', candidate_url=url, forward=forward)
        save()
        promote = '''import pathlib,json,hashlib,fcntl,subprocess,urllib.request
base=pathlib.Path('/etc/cn25-console');lock=(base/'primary-ingress.lock').open('a');fcntl.flock(lock,fcntl.LOCK_EX)
p=pathlib.Path('/etc/nginx/conf.d/cn25-console.conf');before=p.read_bytes()
assert hashlib.sha256(before).hexdigest()==EXPECTED
with urllib.request.urlopen('http://127.0.0.1:%d/health'%FORWARD,timeout=10) as r:assert json.load(r)['version']==VERSION
planned=before.replace(('127.0.0.1:%d'%OLD_FORWARD).encode(),('127.0.0.1:%d'%FORWARD).encode());assert planned!=before
backup=pathlib.Path(BACKUP);assert not backup.exists();backup.write_bytes(before);backup.chmod(0o600)
p.write_bytes(planned)
try:
 subprocess.run(['nginx','-t'],check=True,capture_output=True);subprocess.run(['systemctl','reload','nginx'],check=True,capture_output=True)
except BaseException:
 p.write_bytes(before);subprocess.run(['nginx','-t'],check=True,capture_output=True);subprocess.run(['systemctl','reload','nginx'],check=True,capture_output=True);raise
result={'status':'switched','primary_sha256':hashlib.sha256(planned).hexdigest()}
'''
        parameters = {'EXPECTED': active['primary_sha256'], 'FORWARD': forward_port, 'OLD_FORWARD': active['forward_port'],
                      'VERSION': version, 'BACKUP': '/etc/cn25-console/rev-updates/' + tag + '/primary-before.conf'}
        promoted = remote_job(ssh, tag, 'promote', '\n'.join(k + '=' + repr(v) for k, v in parameters.items()) + '\n' + promote)
        current = {'version': version, 'release': str(release), 'port': port, 'forward_port': forward_port,
                   'unit': unit_name, 'tunnel_unit': tunnel_name, 'primary_sha256': promoted['primary_sha256'],
                   'candidate_sha256': staged['candidate_sha256'], 'commit': manifest['commit']}
        atomic(active_path, current)
        next_link = current_link.with_name('rev-current.next')
        if next_link.exists() or next_link.is_symlink():
            raise RuntimeError('Unrecorded Rev activation link exists')
        next_link.symlink_to(release)
        next_link.replace(current_link)
        if not launcher.exists():
            temporary = launcher.with_name('cloud-cli-rev.next')
            if temporary.exists():
                raise RuntimeError('Unrecorded Rev launcher exists')
            temporary.write_text(launcher_text)
            temporary.chmod(0o755)
            temporary.replace(launcher)
        next_controller = BASE / 'rev-update.py.next'
        next_controller.write_text(controller_source)
        next_controller.chmod(0o600)
        next_controller.replace(BASE / 'rev-update.py')
        state.update(status='applied', active=current, public_url='https://' + config['hostname'] + ':8443',
                     finished_utc=datetime.datetime.now(datetime.timezone.utc).isoformat())
        save()
    except BaseException as error:
        state['error_type'] = type(error).__name__
        if state['status'] != 'needs-remote-readback':
            state['status'] = 'failed-existing-services-preserved'
        save()
        raise


if __name__ == '__main__':
    try:
        main()
    except BaseException as error:
        print(json.dumps({'status': 'inspect-durable-receipt', 'error_type': type(error).__name__}))
        sys.exit(1)
