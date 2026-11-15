#!/bin/bash
set -euo pipefail
umask 077
base=/etc/cn25-console
mkdir -p "$base/acme/dnsapi" "$base/tls"
exec >>"$base/prepare.log" 2>&1
python3 "$base/dns.py" prepare
cp /etc/clash-agent/acme/acme.sh "$base/acme/acme.sh"
chmod 700 "$base/acme/acme.sh"
cat >"$base/acme/dnsapi/dns_cn25_cf.sh" <<'HOOK'
dns_cn25_cf_add() { /usr/bin/python3 /etc/cn25-console/dns.py add "$1" "$2"; }
dns_cn25_cf_rm() { /usr/bin/python3 /etc/cn25-console/dns.py remove "$1" "$2"; }
HOOK
"$base/acme/acme.sh" --issue --home "$base/acme" --config-home "$base/acme" --cert-home "$base/acme" --server letsencrypt --dns dns_cn25_cf -d cn25.foliodude.it.com -k ec-256 --dnssleep 30
"$base/acme/acme.sh" --install-cert --home "$base/acme" --config-home "$base/acme" --cert-home "$base/acme" -d cn25.foliodude.it.com --ecc --fullchain-file "$base/tls/fullchain.pem" --key-file "$base/tls/key.pem" --reloadcmd 'nginx -t && systemctl reload nginx.service'
chmod 600 "$base/tls/key.pem"
openssl x509 -in "$base/tls/fullchain.pem" -noout -checkhost cn25.foliodude.it.com
date -u +%FT%TZ >"$base/prepared-at"
