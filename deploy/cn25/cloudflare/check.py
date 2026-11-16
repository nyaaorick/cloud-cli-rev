#!/usr/bin/python3
"""Read-only local checks; no login, chat, credential reads or external HTTP."""
import argparse
import datetime
import grp
import importlib.util
import json
from pathlib import Path
import pwd
import re
import sys
import urllib.error
import urllib.request

from cf_common import DEFAULT_CONFIG, ROOT, load_config, resolver_text, run, sha, sysusers_text
import guard


def local_response(config, path, metrics=False):
    port = config['metricsPorts'][0] if metrics else config['originPort']
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    return opener.open('http://127.0.0.1:%d%s' % (port, path), timeout=8)


def diagnose(config, allow_legacy=False):
    results = {}
    def check(name, operation):
        try:
            ok, details = operation()
            results[name] = {'ok': bool(ok), 'details': details}
        except Exception as error:
            results[name] = {'ok': False, 'error_type': type(error).__name__}
    def origin():
        with local_response(config, '/health') as response:
            value = json.load(response)
        return value.get('status') == 'ok', {k: value.get(k) for k in ('status', 'version', 'installMode')}
    def anonymous():
        try:
            with local_response(config, '/api/projects') as response:
                status = response.status
        except urllib.error.HTTPError as error:
            status = error.code
        return status == 401, {'status': status}
    def readiness():
        with local_response(config, '/ready', metrics=True) as response:
            value = json.load(response)
        return value.get('status') == 200 and value.get('readyConnections', 0) >= 4, {'connections': value.get('readyConnections')}
    def locations():
        with local_response(config, '/metrics', metrics=True) as response:
            text = response.read(1000000).decode()
        active = set()
        for line in text.splitlines():
            if line.startswith('cloudflared_tunnel_server_locations{'):
                labels, value = line.rsplit(' ', 1)
                match = re.search(r'edge_location="([a-z0-9]+)"', labels)
                if match and float(value) > 0:
                    active.add(match.group(1))
        return len(active) >= 2, {'locations': sorted(active)}
    def services():
        states = {}
        for name in ('appUnit', 'tunnelUnit', 'routeUnit'):
            value = run(['systemctl', 'show', config[name], '-p', 'ActiveState', '-p', 'SubState', '-p', 'MainPID', '-p', 'NRestarts']).decode()
            states[config[name]] = dict(line.split('=', 1) for line in value.splitlines() if '=' in line)
        return all(value.get('ActiveState') == 'active' for value in states.values()), states
    def routing():
        spec = importlib.util.spec_from_file_location('cf_route_check', ROOT / 'direct-route.py')
        route = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(route)
        exact = route.present(config) == set(config['routePriorities'])
        selected = json.loads(run(['/usr/sbin/ip', '-4', '-j', 'route', 'get', config['dnsServers'][0], 'uid', str(config['uid'])]))
        device = selected[0].get('dev') if len(selected) == 1 else None
        return exact and device == config['interface'], {'exact_rules': exact, 'selected_interface': device}
    def dns():
        same = Path(config['resolverFile']).read_text() == resolver_text(config)
        return same, {'matches_configured_resolver': same}
    def firewall():
        value = guard.plan(config)
        return value['mode'] == 'current' or (allow_legacy and value['mode'] == 'legacy'), guard.summary(value)
    def pins():
        guard.preflights(config)
        return True, {'passed': len(config['guardChecks'])}
    def runtime():
        manifest = json.loads((Path(config['runtimeDirectory']) / 'installed-manifest.json').read_text())
        valid = all(sha((Path(config['runtimeDirectory']) / name).read_bytes()) == expected
                    for name, expected in manifest['files'].items())
        return valid, {'installed_files_match': valid, 'cloudflared_version': manifest['cloudflaredVersion']}
    def identity():
        user = pwd.getpwnam(config['user'])
        group = grp.getgrnam(config['group'])
        persistent = Path('/etc/sysusers.d') / (config['user'] + '.conf')
        same = persistent.read_text() == sysusers_text(config)
        valid = user.pw_uid == user.pw_gid == group.gr_gid == config['uid']
        return same and valid, {'uid_gid_match': valid, 'persistent_definition_matches': same}
    for name, operation in [('origin', origin), ('anonymous_api', anonymous), ('tunnel_ready', readiness),
                            ('edge_locations', locations), ('services', services), ('physical_routes', routing),
                            ('private_dns', dns), ('owned_firewall', firewall), ('existing_guards', pins),
                            ('runtime_integrity', runtime), ('persistent_identity', identity)]:
        check(name, operation)
    passed = all(value['ok'] for value in results.values())
    return {'observed_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
            'scope': 'local read-only; public login and browser acceptance are separate',
            'status': 'passed' if passed else 'failed', 'allow_legacy_rules': allow_legacy, 'checks': results}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', default=str(DEFAULT_CONFIG))
    parser.add_argument('--allow-legacy', action='store_true', help='Permit the two known redundant old rules during adoption')
    args = parser.parse_args()
    try:
        result = diagnose(load_config(args.config), args.allow_legacy)
    except Exception as error:
        result = {'status': 'failed', 'error_type': type(error).__name__}
    print(json.dumps(result, indent=2))
    sys.exit(0 if result['status'] == 'passed' else 1)
