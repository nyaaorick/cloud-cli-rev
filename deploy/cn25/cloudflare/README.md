# CN25 physical Cloudflare environment

The console keeps its fixed application service and origin port. Its named
Cloudflare Tunnel runs as a separate UID, binds the physical source address,
uses HTTP/2 over IPv4 and never falls back to TUN, a proxy, a VPS or reverse SSH.
Existing Cloudflare Tunnel/DNS provisioning and authentication are retained.

This module contains the final deployed network policy, configurable runtime
wrappers, systemd units, persistent sysusers identity and read-only diagnostics.
It replaces the collection of dated one-time activation and recovery scripts.
It does not contain credentials, environment files, databases, browser profiles,
session history, raw logs or old deployment receipts.

## Release artifacts

Each Rev release has an optional
`cloud-cli-rev-v<VERSION>-cloudflare-linux-amd64.tar.gz`,
`cloudflare-manifest.json` and `CLOUDFLARE-SHA256SUMS`. The application archive
still uses the original two-entry `SHA256SUMS`, preserving existing updater
compatibility. The environment archive includes only an explicit source
allowlist, tests, configuration and the official cloudflared **2026.11.0** binary.
Its original Apache license and source URL are retained. The binary is not
committed to Git. `artifact.json` pins its download URL and SHA256.

Verify checksums before extracting. The internal `ENVIRONMENT-MANIFEST.json`
records each file digest. Ordinary HTTPS/GitHub repository trust remains the
publisher trust boundary; checksums alone do not authenticate a publisher.

## Configuration and preparation

Review `config.cn25.json` for the actual host. It contains nonsecret service
identity, interface/address, DNS servers, local ports, route priorities, paths
and existing guard integration. Invalid identities, control characters,
conflicting priorities and unsafe nft/systemd substitutions are rejected.
`cloudflare-ips-v4.txt` is the reviewed official IPv4 list; changes to this list
require review and new checksums rather than a live unverified refresh.

The existing shared guard table/anchor and paired guard pin/check scripts must
already exist and agree with the running rules. The connector credential must
already be a regular root-owned0600 file at `tokenFile`; the installer reads
only its metadata. PID1 passes it using `LoadCredential`, and cloudflared reads
the mapped file via `--token-file`. No credential value enters argv or logs.

The installer validates account name/UID/GID conflicts. Missing matching records
are restored through `/etc/sysusers.d/<user>.conf` and `systemd-sysusers`, using
the configured identity. It does not reuse or delete another account.

```sh
sudo -n python3 -B install.py plan --config /path/to/reviewed-profile.json
```

After reviewing the plan, run `install.py apply` with the same arguments in an
independent root systemd maintenance unit. It can use the current pinned binary,
the offline `binary/cloudflared`, or an explicitly supplied `--binary` file.
It does not download privileged runtime code during installation.

For an active tunnel, profile and bind-mounted resolver changes are refused;
schedule a separate controlled restart for such changes. The initial adoption
uses the existing measured profile and resolver. Runtime dependencies are
installed before the wrapper, and neither the application nor the tunnel is
restarted. The existing connector continues its current process until a later
ordinary service restart. Enabling units is persistent only. A fresh inactive
installation additionally requires an operator to start the route unit and
then the tunnel unit after validation; this never starts an extra application.

## Network transaction and cleanup

Only the dedicated UID may reach the local origin/metrics, configured public
DNS, Cloudflare edge TCP/UDP7844 and official Cloudflare HTTPS443/8443. A final
UID-specific drop precedes broader loopback/TUN rules. Route lookup is followed
by an unreachable rule, so a missing physical route cannot fall back to TUN.
Route removal refuses a live dedicated UID. There is no automatic `ExecStop`
route removal.

The installer recognizes exactly the six intended rules and two known older
HTTPS rules covered by the complete official list. It deletes those two
duplicates by exact handles, preserves the remaining rules and unrelated
forwarding, updates persistent text and both guard pins, and runs both native
guard checks. Fresh rule installation is anchored before the existing loopback
accept. Unknown/repeated owned rules, pin conflicts, changed anchors or
persistent/live mismatches fail closed.

Changes hold the existing guard lock and are validated in a disposable network
namespace. A failed post-write check rolls back only owned rules when the exact
expected state still exists. Concurrent/unknown states are preserved with a
`needs-inspection` receipt. No full-chain or full-table restoration is used.

The exact old `90-physical-direct.conf` is removed only after its settings are
present in the generated base unit. Unknown drop-ins are retained. Every
installation attempt records changed-file digests and previous nonsecret
contents under `stateDirectory`; no attempt or failure history is erased.

## Verification

```sh
python3 -B -m unittest discover -s tests -p 'test_*.py'
sudo -n unshare --net -- python3 -B tests/check_isolated.py
sudo -n python3 -B check.py --config /etc/cn25-console-cloudflared/profile.json
```

The isolated integration check refuses the host network namespace. It verifies
real nft deduplication, idempotency, post-write rollback, unrelated forwarding,
route collision protection and absence of TUN fallback.

The read-only command checks `/health`, anonymous API401, four ready connections,
multiple active edge locations, unit state, routing, resolver, intended owned
rules, both existing guards and installed runtime integrity. It performs no
authentication, chat, external HTTP or host modification. Its temporary nft
compilation is confined to a new network namespace. `--allow-legacy` is only for
diagnosing an adopted installation before the two duplicates are removed.

Public HTTPS/login, existing native history, browser refresh and WebSocket
continuity must additionally pass after an application update. Default HTTPS
physical acceptance and legacy8443 client compatibility remain separate
observations. Google Fonts external stylesheets are removed in Rev7; the
existing CSS system-font fallback allows startup under restricted egress.

## Preservation and rollback

Do not rerun dated tunnel creation/DNS promotion scripts, reinitialize owner
state, clean historical failed units, or delete queue/unknown-result records.
Application rollback retains the previous immutable release. Dependency trees
may be shared by symlink: resolve those references before considering any old
release disposable. The current manager CLI, fixed toolchain and home are
outside the change and cleanup sets.

Reverting the network environment is a separate independent maintenance action:
inspect the exact receipt and current state, stop only the dedicated connector
when necessary, hold the existing guard lock, revert only proven owned changes,
update both guard pins and rerun both checks. Never flush a shared ruleset or
restore an entire historical host snapshot.
