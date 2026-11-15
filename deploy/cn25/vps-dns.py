#!/usr/bin/python3
"""Isolated CloudCLI DNS operations; credentials stay in server memory."""
import json
import pathlib
import sys
import urllib.parse
import urllib.request

HOST = 'cn25.foliodude.it.com'
BASE = pathlib.Path('/etc/cn25-console')


def api(method, endpoint, data=None):
    token = pathlib.Path('/etc/clash-agent/cloudflare-token').read_text().strip()
    request = urllib.request.Request(
        'https://api.cloudflare.com/client/v4' + endpoint,
        data=None if data is None else json.dumps(data).encode(),
        headers={'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'},
        method=method,
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            result = json.load(response)
    except Exception:
        raise SystemExit('Cloudflare transport failed; response suppressed')
    if not result.get('success'):
        raise SystemExit('Cloudflare rejected operation; response suppressed')
    return result['result']


def main():
    zones = api('GET', '/zones?name=foliodude.it.com&status=active')
    if len(zones) != 1:
        raise SystemExit('Expected exactly one managed DNS zone')
    zone = zones[0]['id']
    action = sys.argv[1]
    if action == 'prepare':
        existing = api('GET', '/zones/' + zone + '/dns_records?name=' + HOST)
        receipt = BASE / 'dns-receipt.json'
        if existing:
            if not receipt.exists() or [r['id'] for r in existing] != [json.loads(receipt.read_text())['id']]:
                raise SystemExit('Hostname conflict; existing DNS was preserved')
        else:
            result = api('POST', '/zones/' + zone + '/dns_records', {
                'type': 'A', 'name': HOST, 'content': '67.200.126.71',
                'proxied': True, 'ttl': 1, 'comment': 'CN25 CloudCLI independent console',
            })
            receipt.write_text(json.dumps({'zone': zone, 'id': result['id'], 'hostname': HOST}) + '\n')
            receipt.chmod(0o600)
        print('CloudCLI DNS prepared; unrelated records preserved')
    elif action in ('add', 'remove'):
        name, value = sys.argv[2:4]
        if name.rstrip('.') != '_acme-challenge.' + HOST:
            raise SystemExit('Challenge name outside console scope')
        endpoint = '/zones/' + zone + '/dns_records'
        records = api('GET', endpoint + '?type=TXT&name=' + urllib.parse.quote(name))
        matching = [r for r in records if r['content'] == value]
        if action == 'add' and not matching:
            api('POST', endpoint, {'type': 'TXT', 'name': name, 'content': value, 'ttl': 60})
        elif action == 'remove':
            for record in matching:
                api('DELETE', endpoint + '/' + record['id'])
    else:
        raise SystemExit('Unsupported operation')


if __name__ == '__main__':
    main()
