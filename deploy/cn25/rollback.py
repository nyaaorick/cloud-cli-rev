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
import subprocess
base=Path('/etc/cn25-console')
assert (base/'published.json').exists(), 'No owned publication receipt'
p=Path('/etc/nginx/conf.d/cn25-console.conf')
if p.exists():
    assert p.read_bytes()==(base/'nginx.conf').read_bytes(), 'Vhost changed; preserve for inspection'
    p.rename(base/'rolled-back-nginx.conf')
    subprocess.run(['nginx','-t'],check=True)
    subprocess.run(['systemctl','reload','nginx.service'],check=True)
PY'''
subprocess.run(ssh + [remote], check=True)
subprocess.run(['systemctl', 'disable', '--now'] + receipt['stop_only'], check=True)
(base / 'rolled-back.json').write_text(json.dumps({'console_units_stopped': receipt['stop_only'], 'all_history_and_credentials_retained': True}) + '\n')
