#!/usr/bin/python3
"""Run only in a separate root systemd unit; retain all console/native state."""
import json
import pathlib
import subprocess

base = pathlib.Path('/srv/review/controller/cloudcli-first-20261115')
receipt = json.loads((base / 'rollback.json').read_text())
assert receipt['stop_only'] == ['cn25-console.service', 'cn25-console-tunnel.service']
ssh = ['/usr/bin/ssh', '-F', '/srv/review/secrets/manager-access/ssh_config', 'console-vps']
remote = '''python3 - <<'PY'
from pathlib import Path
import subprocess,json,hashlib
base=Path('/etc/cn25-console')
p=Path('/etc/nginx/conf.d/cn25-console.conf')
if p.exists():
    intent=json.loads((base/'publish-intent.json').read_text())
    content=p.read_bytes()
    assert hashlib.sha256(content).hexdigest()==intent['planned_sha256'], 'Vhost changed; preserve for inspection'
    if intent['previous_exists']:
        previous=(base/'previous-nginx.conf').read_bytes()
        assert hashlib.sha256(previous).hexdigest()==intent['previous_sha256']
        p.write_bytes(previous)
    else:
        p.rename(base/'rolled-back-nginx.conf')
    try:
        subprocess.run(['nginx','-t'],check=True)
        subprocess.run(['systemctl','reload','nginx.service'],check=True)
    except Exception:
        p.write_bytes(content)
        raise
PY'''
remote_ok = False
try:
    subprocess.run(ssh + [remote], check=True, timeout=60)
    remote_ok = True
finally:
    installed = [u for u in receipt['stop_only'] if pathlib.Path('/etc/systemd/system', u).exists()]
    if installed:
        subprocess.run(['systemctl', 'disable', '--now'] + installed, check=True)
    (base / 'rolled-back.json').write_text(json.dumps({'console_units_stopped': installed, 'remote_vhost_rollback_confirmed': remote_ok, 'all_history_and_credentials_retained': True}) + '\n')
