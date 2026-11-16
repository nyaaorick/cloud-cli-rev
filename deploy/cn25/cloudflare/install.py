#!/usr/bin/python3
"""Adopt or refresh the dedicated tunnel environment; preserve active processes."""
import argparse
import datetime
import fcntl
import grp
import importlib.util
import json
import os
from pathlib import Path
import pwd
import stat
import sys
import tempfile

from cf_common import ROOT, atomic, load_config, resolver_text, run, sha, sysusers_text, unit_files
import guard

RUNTIME_FILES = ('cf_common.py', 'config.cn25.json', 'artifact.json', 'cloudflare-ips-v4.txt',
                 'cloudflared-LICENSE', 'guard.py', 'check.py', 'direct-route.py', 'connector.py')


def public_directory(path):
    path = Path(path)
    missing = []
    current = path
    while not current.exists():
        missing.append(current)
        current = current.parent
    if current.is_symlink() or not current.is_dir():
        raise RuntimeError('Unsafe public directory ancestor')
    for item in reversed(missing):
        item.mkdir(mode=0o755)
        item.chmod(0o755)
    if path.is_symlink() or not path.is_dir():
        raise RuntimeError('Unsafe public directory')
    path.chmod(0o755)


def identity(config):
    found = {}
    for key, lookup, argument in [('user_name', pwd.getpwnam, config['user']), ('user_id', pwd.getpwuid, config['uid']),
                                  ('group_name', grp.getgrnam, config['group']), ('group_id', grp.getgrgid, config['uid'])]:
        try:
            found[key] = lookup(argument)
        except KeyError:
            found[key] = None
    for key in ('user_name', 'user_id'):
        user = found[key]
        if user is not None and (user.pw_name != config['user'] or user.pw_uid != config['uid'] or user.pw_gid != config['uid']):
            raise RuntimeError('Dedicated user conflict preserved')
    for key in ('group_name', 'group_id'):
        group = found[key]
        if group is not None and (group.gr_name != config['group'] or group.gr_gid != config['uid']):
            raise RuntimeError('Dedicated group conflict preserved')
    addresses = json.loads(run(['/usr/sbin/ip', '-4', '-j', 'address', 'show', 'dev', config['interface']]))
    if not any(item.get('local') == config['bindAddress'] for link in addresses for item in link.get('addr_info', [])):
        raise RuntimeError('Bind address does not belong to the physical interface')
    token = Path(config['tokenFile']).lstat()
    if not stat.S_ISREG(token.st_mode) or token.st_uid != 0 or stat.S_IMODE(token.st_mode) != 0o600:
        raise RuntimeError('Root0600 connector credential file required')
    # Inspect only credential file metadata. PID1/cloudflared alone read its value.
    return 'present' if all(found.values()) else 'needs-sysusers'


def binary(config, supplied=None):
    path = Path(supplied) if supplied else Path(config['runtimeDirectory']) / 'cloudflared'
    if not path.is_file() and supplied is None:
        path = ROOT / 'binary/cloudflared'
    artifact = json.loads((ROOT / 'artifact.json').read_text())
    if path.is_symlink() or sha(path.read_bytes()) != artifact['sha256']:
        raise RuntimeError('Pinned cloudflared binary mismatch')
    return path, artifact


def legacy_dropin(config):
    return ('''[Unit]
Requires={routeUnit}
After={routeUnit}
[Service]
DynamicUser=no
User={user}
Group={group}
BindReadOnlyPaths={resolverFile}:/etc/resolv.conf
RestrictNetworkInterfaces={interface} lo
UnsetEnvironment=HTTP_PROXY HTTPS_PROXY ALL_PROXY http_proxy https_proxy all_proxy
'''.format(**config)).encode()


def files(config, binary_path):
    runtime = Path(config['runtimeDirectory'])
    values = {Path('/etc/sysusers.d') / (config['user'] + '.conf'): sysusers_text(config).encode(),
              Path(config['configFile']): (json.dumps(config, indent=2) + '\n').encode()}
    values.update({runtime / name: (ROOT / name).read_bytes() for name in RUNTIME_FILES})
    values[runtime / 'cloudflared'] = binary_path.read_bytes()
    values[Path(config['resolverFile'])] = resolver_text(config).encode()
    values.update({Path('/etc/systemd/system') / name: value.encode() for name, value in unit_files(config).items()})
    return values


def preflight(config, binary_path):
    identity(config)
    guard.preflights(config)
    route_spec = importlib.util.spec_from_file_location('cf_preflight_route', ROOT / 'direct-route.py')
    route = importlib.util.module_from_spec(route_spec)
    route_spec.loader.exec_module(route)
    route.present(config)
    profile = Path(config['configFile'])
    active = run(['systemctl', 'show', config['tunnelUnit'], '-p', 'ActiveState', '--value']).strip() == b'active'
    if active and profile.exists() and json.loads(profile.read_text()) != config:
        raise RuntimeError('Active profile differs; arrange a separate controlled restart')
    resolver = Path(config['resolverFile'])
    if active and resolver.exists() and resolver.read_text() != resolver_text(config):
        raise RuntimeError('Active bind-mounted resolver differs; preserve its inode and arrange maintenance')
    if active:
        properties = run(['systemctl', 'show', config['tunnelUnit'], '-p', 'User', '-p', 'Group']).decode()
        found = dict(line.split('=', 1) for line in properties.splitlines() if '=' in line)
        if found != {'User': config['user'], 'Group': config['group']}:
            raise RuntimeError('Active tunnel identity conflict')
    dropin = Path('/etc/systemd/system') / (config['tunnelUnit'] + '.d') / '90-physical-direct.conf'
    if dropin.exists() and (dropin.is_symlink() or dropin.read_bytes() != legacy_dropin(config)):
        raise RuntimeError('Unrecognized existing physical drop-in preserved')
    values = files(config, binary_path)
    for directory in [Path(config['runtimeDirectory']), Path(config['configFile']).parent,
                      Path(config['resolverFile']).parent, Path('/etc/sysusers.d')]:
        if directory.exists() and (directory.is_symlink() or not directory.is_dir() or
                                   directory.stat().st_uid != 0 or directory.stat().st_mode & 0o022):
            raise RuntimeError('Untrusted runtime directory preserved')
    for path in values:
        if path.is_symlink():
            raise RuntimeError('Symlink target preserved')
        if path.exists() and (not path.is_file() or path.stat().st_uid != 0 or path.stat().st_mode & 0o022):
            raise RuntimeError('Untrusted installed file preserved')
    return values, dropin, active


def install(config, binary_path):
    values, dropin, active = preflight(config, binary_path)
    # Validate all network changes before touching installed files.
    planned = guard.plan(config)
    state = Path(config['stateDirectory'])
    state.mkdir(parents=True, exist_ok=True, mode=0o700)
    attempt = Path(tempfile.mkdtemp(prefix='install-', dir=str(state)))
    receipt = {'status': 'prepared', 'started_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
               'guard_plan': guard.summary(planned), 'changed_files': [], 'tunnel_was_active': active,
               'restarted_services': [], 'credential_values_read': False}
    def save():
        atomic(attempt / 'receipt.json', (json.dumps(receipt, indent=2) + '\n').encode(), 0o600)
    save()
    try:
        for directory in [Path(config['runtimeDirectory']), Path(config['configFile']).parent,
                          Path(config['resolverFile']).parent, Path('/etc/sysusers.d')]:
            public_directory(directory)
        receipt['identity_before'] = identity(config)
        before = {}
        for index, (path, data) in enumerate(values.items()):
            if path.exists() and path.read_bytes() == data:
                continue
            before[str(path)] = sha(path.read_bytes()) if path.exists() else None
            if path.exists():
                atomic(attempt / ('file-%d.before' % index), path.read_bytes(), 0o600)
            atomic(path, data, 0o755 if path.name == 'cloudflared' else 0o644)
            receipt['changed_files'].append({'path': str(path), 'before_sha256': before[str(path)], 'after_sha256': sha(data)})
        run(['systemd-sysusers', str(Path('/etc/sysusers.d') / (config['user'] + '.conf'))])
        if identity(config) != 'present':
            raise RuntimeError('Persistent dedicated identity was not established')
        runtime = Path(config['runtimeDirectory'])
        manifest = {'cloudflaredVersion': json.loads((ROOT / 'artifact.json').read_text())['version'],
                    'files': {name: sha((runtime / name).read_bytes()) for name in (*RUNTIME_FILES, 'cloudflared')}}
        manifest_bytes = (json.dumps(manifest, indent=2) + '\n').encode()
        manifest_path = runtime / 'installed-manifest.json'
        if not manifest_path.exists() or manifest_path.read_bytes() != manifest_bytes:
            atomic(manifest_path, manifest_bytes)
        receipt['guard'] = guard.apply(config)
        route_spec = importlib.util.spec_from_file_location('cf_install_route', runtime / 'direct-route.py')
        route = importlib.util.module_from_spec(route_spec)
        route_spec.loader.exec_module(route)
        route.main('apply', config)
        if dropin.exists():
            atomic(attempt / 'redundant-dropin.before', dropin.read_bytes(), 0o600)
            # The generated base unit includes every setting in this exact drop-in.
            if dropin.read_bytes() != legacy_dropin(config):
                raise RuntimeError('Concurrent drop-in change preserved')
            dropin.unlink()
            receipt['removed_redundant_dropin'] = str(dropin)
        unit_paths = [str(Path('/etc/systemd/system') / name) for name in unit_files(config)]
        run(['systemd-analyze', 'verify', *unit_paths])
        if receipt['changed_files'] or receipt.get('removed_redundant_dropin'):
            run(['systemctl', 'daemon-reload'])
        run(['systemctl', 'enable', config['routeUnit'], config['tunnelUnit']])
        # Enabling is persistent only. Existing tunnel/app processes are never restarted.
        receipt.update(status='installed', finished_utc=datetime.datetime.now(datetime.timezone.utc).isoformat())
    except BaseException as error:
        receipt.update(status='needs-inspection', error_type=type(error).__name__)
        save()
        raise
    save()
    return dict(receipt, receipt=str(attempt / 'receipt.json'))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['plan', 'apply'])
    parser.add_argument('--config', default=str(ROOT / 'config.cn25.json'))
    parser.add_argument('--binary', help='Existing or offline pinned binary; its content must match artifact.json')
    args = parser.parse_args()
    try:
        if os.geteuid() != 0:
            raise PermissionError('Use an independent root maintenance unit')
        os.umask(0o077)
        config = load_config(args.config)
        selected, artifact = binary(config, args.binary)
        if args.action == 'plan':
            preflight(config, selected)
            result = dict(guard.summary(guard.plan(config)), status='planned', binary_version=artifact['version'],
                          binary_sha256_verified=True, credential_values_read=False, identity_state=identity(config))
        else:
            state = Path(config['stateDirectory'])
            state.mkdir(parents=True, exist_ok=True, mode=0o700)
            with (state / 'environment.lock').open('a') as lock:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                result = install(config, selected)
        print(json.dumps(result, indent=2))
    except Exception as error:
        print(json.dumps({'status': 'inspect-environment-receipts', 'error_type': type(error).__name__}))
        sys.exit(1)
