#!/usr/bin/python3
"""Own exactly one UID lookup and one unreachable rule; preserve conflicts."""
import argparse
import json
import subprocess
import sys

from cf_common import DEFAULT_CONFIG, load_config, run


def expected(config, priority):
    value = {'priority': priority, 'src': 'all', 'uid_start': config['uid'], 'uid_end': config['uid']}
    value.update({'table': 'main'} if priority == config['routePriorities'][0] else {'action': 'unreachable'})
    return value


def present(config):
    found = set()
    for rule in json.loads(run(['/usr/sbin/ip', '-4', '-j', 'rule', 'show'])):
        priority = rule.get('priority')
        if priority not in config['routePriorities']:
            continue
        if rule != expected(config, priority) or priority in found:
            raise RuntimeError('Route identity conflict preserved')
        found.add(priority)
    return found


def change(config, operation, priority):
    run(['/usr/sbin/ip', '-4', 'rule', operation, 'priority', str(priority), 'uidrange',
         '%d-%d' % (config['uid'], config['uid']),
         *(['lookup', 'main'] if priority == config['routePriorities'][0] else ['unreachable'])])


def main(mode, config):
    existing = present(config)
    if mode == 'remove':
        # The operator must first stop all processes using this identity.
        result = subprocess.run(['/usr/bin/pgrep', '-u', str(config['uid'])], capture_output=True, timeout=10)
        if result.returncode == 0:
            raise RuntimeError('Dedicated identity still has processes')
        if result.returncode != 1:
            raise RuntimeError('Unable to establish whether the identity is idle')
        for priority in config['routePriorities']:
            if priority in existing:
                change(config, 'del', priority)
        return
    if mode != 'apply':
        raise ValueError('Expected apply or remove')
    added = []
    try:
        # Refusal exists before installing the bypass rule.
        for priority in reversed(config['routePriorities']):
            if priority not in existing:
                change(config, 'add', priority)
                added.append(priority)
        if present(config) != set(config['routePriorities']):
            raise RuntimeError('Incomplete physical-only routes')
    except BaseException:
        for priority in reversed(added):
            change(config, 'del', priority)
        raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['apply', 'remove'])
    parser.add_argument('--config', default=str(DEFAULT_CONFIG))
    args = parser.parse_args()
    try:
        main(args.action, load_config(args.config))
    except Exception as error:
        print(json.dumps({'status': 'route-failed', 'error_type': type(error).__name__}))
        sys.exit(1)
