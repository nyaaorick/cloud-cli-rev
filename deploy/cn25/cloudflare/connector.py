#!/usr/bin/python3
"""Run the pinned connector while emitting only allowlisted operational fields."""
import argparse
import ipaddress
import json
import os
import re
import signal
import subprocess
import sys

from cf_common import DEFAULT_CONFIG, load_config


def summarize(line):
    try:
        source = json.loads(line)
    except (ValueError, TypeError):
        return None
    if not isinstance(source, dict):
        return None
    event = 'connector-event'
    message = str(source.get('message', '')).lower()
    for needle, name in [
        ('unregistered tunnel connection', 'connection-unregistered'),
        ('registered tunnel connection', 'connection-registered'),
        ('failed to serve', 'connection-error'),
        ('unable to establish', 'edge-dial-failed'),
        ('retrying connection', 'connection-retry'),
        ('unable to reach the origin', 'origin-unavailable'),
        ('updated to new configuration', 'configuration-updated'),
        ('starting tunnel', 'connector-started'),
        ('initiating graceful shutdown', 'connector-stopping'),
    ]:
        if needle in message:
            event = name
            break
    safe = {'event': event}
    if source.get('level') in ('trace', 'debug', 'info', 'warn', 'error', 'fatal', 'panic'):
        safe['level'] = source['level']
    if type(source.get('connIndex')) is int:
        safe['connection'] = source['connIndex']
    if source.get('protocol') in ('quic', 'http2'):
        safe['protocol'] = source['protocol']
    if re.fullmatch('[a-z]{3}[0-9]{0,3}', str(source.get('location', ''))):
        safe['location'] = source['location']
    try:
        safe['edge_ip'] = str(ipaddress.ip_address(source['ip']))
    except (KeyError, ValueError, TypeError):
        pass
    return safe


def command(config, credential):
    return [config['runtimeDirectory'] + '/cloudflared', 'tunnel', '--no-autoupdate',
            '--edge-ip-version', '4', '--protocol', 'http2',
            '--edge-bind-address', config['bindAddress'], '--metrics',
            '127.0.0.1:%d' % config['metricsPorts'][0], '--loglevel', 'info',
            '--output', 'json', 'run', '--token-file', credential]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('credential', help='systemd credential file path; never a token value')
    parser.add_argument('--config', default=str(DEFAULT_CONFIG))
    args = parser.parse_args()
    config = load_config(args.config)
    if os.getuid() != config['uid']:
        raise RuntimeError('Dedicated physical-only service identity required')
    child = subprocess.Popen(command(config, args.credential), stdout=subprocess.PIPE,
                             stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL)
    def forward(signum, _frame):
        if child.poll() is None:
            child.send_signal(signum)
    signal.signal(signal.SIGTERM, forward)
    signal.signal(signal.SIGINT, forward)
    for line in child.stdout:
        item = summarize(line)
        if item:
            print(json.dumps(item), flush=True)
    return child.wait()


if __name__ == '__main__':
    try:
        sys.exit(main())
    except Exception as error:
        print(json.dumps({'status': 'connector-failed', 'error_type': type(error).__name__}))
        sys.exit(1)
