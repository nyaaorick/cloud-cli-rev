#!/usr/bin/python3
"""Exercise real nft/ip transactions only in a disposable network namespace."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from cf_common import load_config, rules, run, sha
import guard


def main():
    if os.geteuid() != 0 or os.stat('/proc/self/ns/net').st_ino == os.stat('/proc/1/ns/net').st_ino:
        raise RuntimeError('Run only with sudo unshare --net; host network changes are forbidden')
    config = load_config(ROOT / 'config.cn25.json')
    config['uid'] = 60001
    config['interface'] = 'phys-test'
    spec = importlib.util.spec_from_file_location('cf_isolated_route', ROOT / 'direct-route.py')
    route = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(route)
    with tempfile.TemporaryDirectory(prefix='cn25-cf-integration-') as temporary:
        base = Path(temporary)
        config.update(guardFile=str(base / 'guard.nft'), guardLock=str(base / 'guard.lock'),
                      stateDirectory=str(base / 'state'), guardPins=[str(base / 'one.pin'), str(base / 'two.pin')],
                      guardChecks=[str(base / 'check.py'), str(base / 'check.py')])
        checker = ('import hashlib,pathlib,subprocess\n'
                   'value=hashlib.sha256(subprocess.check_output(["nft","-s","list","chain","inet","cn25_us_egress","output"])).hexdigest()\n'
                   'assert all(pathlib.Path(p).read_text().strip()==value for p in ' + repr(config['guardPins']) + ')\n')
        (base / 'check.py').write_text(checker)
        canonical = rules(config)
        old = [*canonical[:-1], *guard.legacy_expressions(config), canonical[-1]]
        initial = ('table inet cn25_us_egress {\n chain output {\n type filter hook output priority 0; policy accept;\n'
                   'counter accept comment "unrelated first"\n' + '\n'.join(old) + '\n'
                   'oifname "lo" counter accept comment "IPv4 loopback services only"\n}\n'
                   'chain forward { type filter hook forward priority 0; policy accept; counter accept comment "unrelated forward"\n}\n}\n').encode()
        def start():
            Path(config['guardFile']).write_bytes(initial)
            run(['nft', '-f', config['guardFile']])
            for name in config['guardPins']:
                Path(name).write_text(sha(guard.chain()) + '\n')
        start()
        forward = run(['nft', '-s', 'list', 'chain', 'inet', 'cn25_us_egress', 'forward'])
        first = guard.apply(config)
        assert first['status'] == 'applied' and first['redundant_rules_to_remove'] == 2
        assert guard.plan(config)['mode'] == 'current'
        assert guard.apply(config)['status'] == 'unchanged'
        assert run(['nft', '-s', 'list', 'chain', 'inet', 'cn25_us_egress', 'forward']) == forward
        # Reset only this disposable namespace, then inject a real post-write failure.
        run(['nft', 'delete', 'table', 'inet', 'cn25_us_egress'])
        start()
        before = guard.chain()
        real_preflight = guard.preflights
        calls = []
        def injected(value):
            calls.append(True)
            if len(calls) == 2:
                raise RuntimeError('Synthetic post-transaction guard failure')
            return real_preflight(value)
        with patch.object(guard, 'preflights', injected):
            try:
                guard.apply(config)
            except RuntimeError:
                pass
            else:
                raise AssertionError('Injected failure was hidden')
        assert guard.chain() == before and Path(config['guardFile']).read_bytes() == initial
        assert any(json.loads(path.read_text())['status'] == 'rolled-back'
                   for path in Path(config['stateDirectory']).glob('guard-*/receipt.json'))
        real_preflight(config)
        run(['ip', 'link', 'add', 'tun-test', 'type', 'dummy'])
        run(['ip', 'link', 'set', 'tun-test', 'up'])
        run(['ip', '-4', 'route', 'add', 'default', 'dev', 'tun-test', 'table', '2022'])
        run(['ip', '-4', 'rule', 'add', 'priority', '9000', 'lookup', '2022'])
        route.main('apply', config)
        route.main('apply', config)
        assert subprocess.run(['ip', '-4', 'route', 'get', '1.1.1.1', 'uid', '60001'], capture_output=True).returncode != 0
        assert b'tun-test' in run(['ip', '-4', 'route', 'get', '1.1.1.1', 'uid', '60002'])
        run(['ip', 'link', 'add', 'phys-test', 'type', 'dummy'])
        run(['ip', 'link', 'set', 'phys-test', 'up'])
        run(['ip', '-4', 'route', 'add', 'default', 'dev', 'phys-test'])
        assert b'phys-test' in run(['ip', '-4', 'route', 'get', '1.1.1.1', 'uid', '60001'])
        route.main('remove', config)
        assert not route.present(config)
        run(['ip', '-4', 'rule', 'add', 'priority', '8988', 'uidrange', '60002-60002', 'lookup', 'main'])
        try:
            route.main('apply', config)
        except RuntimeError:
            pass
        else:
            raise AssertionError('Conflicting route was overwritten')
    print(json.dumps({'status': 'passed', 'scope': 'disposable network namespace', 'legacy_rule_deduplication': True,
                      'idempotent_firewall': True, 'post_write_rollback': True, 'unrelated_forward_preserved': True,
                      'route_idempotency': True, 'no_tun_fallback': True, 'physical_selection': True,
                      'precise_remove': True, 'route_conflict_preserved': True}))


if __name__ == '__main__':
    main()
