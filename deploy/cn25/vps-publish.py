#!/usr/bin/python3
"""Publish only the independently staged console vhost, with local rollback."""
import datetime
import hashlib
import json
import pathlib
import subprocess
import urllib.request

base = pathlib.Path('/etc/cn25-console')
target = pathlib.Path('/etc/nginx/conf.d/cn25-console.conf')
if target.exists() and not (base / 'published.json').exists():
    raise SystemExit('Unowned nginx vhost exists; preserved')
with urllib.request.urlopen('http://127.0.0.1:13301/api/auth/status', timeout=15) as response:
    assert json.load(response)['needsSetup'] is False, 'Owner must exist before exposure'
previous = target.read_bytes() if target.exists() else None
planned = (base / 'nginx.conf').read_bytes()
if previous is not None:
    (base / 'previous-nginx.conf').write_bytes(previous)
intent = {'target': str(target), 'planned_sha256': hashlib.sha256(planned).hexdigest(), 'previous_exists': previous is not None, 'previous_sha256': hashlib.sha256(previous).hexdigest() if previous is not None else None}
intent_path = base / 'publish-intent.json'
temporary = base / 'publish-intent.json.tmp'
temporary.write_text(json.dumps(intent) + '\n')
temporary.chmod(0o600)
temporary.replace(intent_path)
try:
    target.write_bytes(planned)
    target.chmod(0o644)
    subprocess.run(['nginx', '-t'], check=True)
    subprocess.run(['systemctl', 'reload', 'nginx.service'], check=True)
except Exception:
    if previous is None:
        target.unlink(missing_ok=True)
    else:
        target.write_bytes(previous)
    raise
pathlib.Path('/etc/systemd/system/cn25-console-cert-renew.service').write_text('''[Unit]
Description=Renew isolated CN25 CloudCLI certificate
[Service]
Type=oneshot
UMask=0077
ExecStart=/etc/cn25-console/acme/acme.sh --cron --home /etc/cn25-console/acme --config-home /etc/cn25-console/acme --cert-home /etc/cn25-console/acme
StandardOutput=append:/etc/cn25-console/renew.log
StandardError=append:/etc/cn25-console/renew.log
''')
pathlib.Path('/etc/systemd/system/cn25-console-cert-renew.timer').write_text('''[Unit]
Description=Check CN25 CloudCLI certificate twice daily
[Timer]
OnCalendar=*-*-* 01,13:00:00
RandomizedDelaySec=45m
Persistent=true
[Install]
WantedBy=timers.target
''')
subprocess.run(['systemctl', 'daemon-reload'], check=True)
subprocess.run(['systemctl', 'enable', '--now', 'cn25-console-cert-renew.timer'], check=True)
(base / 'published.json').write_text(json.dumps({'url': 'https://cn25.foliodude.it.com:8443', 'at': datetime.datetime.now(datetime.timezone.utc).isoformat(), 'vhost': str(target), 'owner_preprovisioned': True}) + '\n')
print('CloudCLI vhost published with nginx validation and graceful reload')
