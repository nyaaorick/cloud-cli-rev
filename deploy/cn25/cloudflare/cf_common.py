"""Validated nonsecret configuration shared by CN25 tunnel maintenance tools."""
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parent
DEFAULT_CONFIG = Path('/etc/cn25-console-cloudflared/profile.json')
NFT_CHAIN = ['inet', 'cn25_us_egress', 'output']


def run(args, data=None, timeout=30):
    return subprocess.run(args, input=data, check=True, capture_output=True, timeout=timeout).stdout


def sha(data):
    return hashlib.sha256(data).hexdigest()


def load_config(path=DEFAULT_CONFIG):
    value = json.loads(Path(path).read_text())
    required = set(json.loads((ROOT / 'config.cn25.json').read_text()))
    if set(value) != required or value['schemaVersion'] != 1:
        raise ValueError('Configuration schema mismatch')
    for name in ('user', 'group'):
        if not re.fullmatch('[a-z_][a-z0-9_-]{0,30}', value[name]):
            raise ValueError('Invalid service identity')
    if type(value['uid']) is not int or not 1 <= value['uid'] < 2 ** 31:
        raise ValueError('Invalid service UID')
    if not re.fullmatch('[A-Za-z0-9_.-]{1,15}', value['interface']) or value['interface'] == 'lo':
        raise ValueError('Invalid physical interface')
    ipaddress.IPv4Address(value['bindAddress'])
    for name in ('dnsServers', 'edgeNetworks'):
        if not value[name] or len(value[name]) != len(set(value[name])):
            raise ValueError('Invalid network list')
        for item in value[name]:
            address = ipaddress.IPv4Address(item) if name == 'dnsServers' else ipaddress.IPv4Network(item)
            if not address.is_global:
                raise ValueError('Public destinations required')
    ports = [value['originPort'], *value['metricsPorts']]
    if (not value['metricsPorts'] or len(set(ports)) != len(ports) or
            any(type(n) is not int or not 1 <= n <= 65535 for n in ports + value['httpsPorts'])):
        raise ValueError('Invalid ports')
    if not value['httpsPorts'] or len(set(value['httpsPorts'])) != len(value['httpsPorts']):
        raise ValueError('Invalid HTTPS ports')
    priorities = value['routePriorities']
    if (len(priorities) != 2 or any(type(n) is not int or not 1 <= n < 32766 for n in priorities)
            or priorities[0] >= priorities[1]):
        raise ValueError('Invalid routing priorities')
    for name in ('tunnelUnit', 'routeUnit', 'guardUnit', 'appUnit'):
        if not re.fullmatch('[a-zA-Z0-9_-]+\\.service', value[name]):
            raise ValueError('Invalid unit name')
    for name in ('ruleCommentPrefix', 'anchorComment'):
        if not re.fullmatch('[A-Za-z0-9 _-]{1,100}', value[name]):
            raise ValueError('Invalid rule comment')
    if not re.fullmatch('[a-zA-Z0-9.-]{1,253}', value['primaryHostname']):
        raise ValueError('Invalid hostname')
    path_names = ('runtimeDirectory', 'configFile', 'resolverFile', 'tokenFile', 'guardFile', 'guardLock', 'stateDirectory')
    for item in [*(value[n] for n in path_names), *value['guardPins'], *value['guardChecks']]:
        if not re.fullmatch('/[a-zA-Z0-9_./-]+', item) or '..' in Path(item).parts:
            raise ValueError('Invalid absolute path')
    if not value['guardPins'] or len(value['guardPins']) != len(value['guardChecks']):
        raise ValueError('Guard checks and pins must be paired')
    return value


def atomic(path, data, mode=0o644):
    path = Path(path)
    if path.is_symlink():
        raise RuntimeError('Symlink destination preserved')
    path.parent.mkdir(parents=True, exist_ok=True)
    previous = path.stat() if path.exists() else None
    fd, temporary = tempfile.mkstemp(prefix='.cn25-cf-', dir=str(path.parent))
    try:
        with os.fdopen(fd, 'wb') as stream:
            os.fchmod(stream.fileno(), mode)
            if previous:
                os.fchown(stream.fileno(), previous.st_uid, previous.st_gid)
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def resolver_text(config):
    return ''.join('nameserver ' + server + '\n' for server in config['dnsServers']) + 'options timeout:3 attempts:2\n'


def official_networks():
    values = (ROOT / 'cloudflare-ips-v4.txt').read_text().splitlines()
    if not values or len(values) != len(set(values)):
        raise ValueError('Invalid pinned Cloudflare network list')
    return [str(ipaddress.IPv4Network(value)) for value in values]


def rules(config):
    prefix = config['ruleCommentPrefix']
    uid = 'meta skuid %d ' % config['uid']
    physical = uid + 'oifname "' + config['interface'] + '" '
    def rule(body, name):
        return body + ' counter ' + ('drop' if name == 'forbid TUN and proxies' else 'accept') + ' comment "' + prefix + ' ' + name + '"'
    nft_set = lambda values: '{ ' + ', '.join(map(str, values)) + ' }'
    return [
        rule(uid + 'oifname "lo" ip daddr 127.0.0.1 tcp dport %d' % config['originPort'], 'origin'),
        rule(uid + 'oifname "lo" ip daddr 127.0.0.1 tcp sport ' + nft_set(config['metricsPorts']), 'metrics'),
        rule(physical + 'ip daddr ' + nft_set(config['dnsServers']) + ' meta l4proto { tcp, udp } th dport 53', 'DNS'),
        rule(physical + 'ip daddr ' + nft_set(config['edgeNetworks']) + ' meta l4proto { tcp, udp } th dport 7844', 'edges'),
        rule(physical + 'ip daddr ' + nft_set(official_networks()) + ' tcp dport ' + nft_set(config['httpsPorts']), 'official HTTPS ranges'),
        rule(uid.rstrip(), 'forbid TUN and proxies'),
    ]


def normalize_rule(value):
    return {key: ([item for item in data if 'counter' not in item] if key == 'expr' else data)
            for key, data in value.items() if key not in ('handle', 'index')}


def unit_files(config):
    route = '''[Unit]
Description=Physical-only routing for the dedicated CN25 Cloudflare identity
Wants=network-online.target
After=network-online.target systemd-sysusers.service {guardUnit}
Before={tunnelUnit}
[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/usr/bin/python3 {runtimeDirectory}/direct-route.py apply --config {configFile}
ExecReload=/usr/bin/python3 {runtimeDirectory}/direct-route.py apply --config {configFile}
# No ExecStop: a running identity must never silently fall back to TUN.
[Install]
WantedBy=multi-user.target
'''.format(**config)
    tunnel = '''[Unit]
Description=CN25 authenticated console direct Cloudflare Tunnel
Wants=network-online.target
Requires={routeUnit}
After=network-online.target systemd-sysusers.service {appUnit} {routeUnit}
StartLimitIntervalSec=0
[Service]
Type=simple
DynamicUser=no
User={user}
Group={group}
BindReadOnlyPaths={resolverFile}:/etc/resolv.conf
RestrictNetworkInterfaces={interface} lo
UnsetEnvironment=HTTP_PROXY HTTPS_PROXY ALL_PROXY http_proxy https_proxy all_proxy
LoadCredential=tunnel-token:{tokenFile}
ExecStart=/usr/bin/python3 {runtimeDirectory}/connector.py %d/tunnel-token --config {configFile}
Restart=always
RestartSec=5s
TimeoutStopSec=40s
UMask=0077
NoNewPrivileges=yes
CapabilityBoundingSet=
ProtectSystem=strict
ProtectHome=yes
PrivateTmp=yes
PrivateDevices=yes
ProtectKernelTunables=yes
ProtectKernelModules=yes
ProtectControlGroups=yes
RestrictSUIDSGID=yes
RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6
LockPersonality=yes
StandardOutput=journal
StandardError=journal
[Install]
WantedBy=multi-user.target
'''.format(**config)
    return {config['routeUnit']: route, config['tunnelUnit']: tunnel}


def sysusers_text(config):
    return ('g {group} {uid} -\n'
            'u {user} {uid}:{group} "CN25 Cloudflare connector" /nonexistent /sbin/nologin\n').format(**config)
