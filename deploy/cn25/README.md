# CN25 CloudCLI first consumer

Upstream: v1.37.8, `2053f3d7a086fd44f7fe373c913da487629b0a95`.
Retains the upstream AGPL license and Git history.

The manager console uses its existing `cn25-manager` account, native fixed CLI,
and independent CODEX_HOME. PID1 reads the root-only Bifrost EnvironmentFile.
Manager mode validates the accepted 6.1 Sol/xhigh profile, pins the model,
permissions, provider and developer role for new/resumed/forked conversations,
and reports custom-provider readiness only after real native inference.
Side questions keep the manager role while retaining upstream's read-only
side-conversation tool boundary. No OAuth login is fabricated.

Build with Node 22 and the upstream lockfile; set VITE_CN25_MANAGER_MODE=1.
The new manager regression fails against the upstream runtime's bundled-CLI
selection. Run typecheck, backend/client tests, build and lint. A one-line fix
to an upstream sidebar test fixture supplies its missing background-session set.

Commit source, obtain independent native review on that SHA and record private
review-approved.json/tests-approved.json in the controller evidence directory.
Start deploy.py in a separate root systemd unit. It builds a versioned root-owned
artifact, saves its SHA256 and rollback receipt, installs only the two console
units, provisions the single owner on loopback, confirms BF inference, then
opens the isolated reverse tunnel and requests an independent VPS publication
unit. The public vhost is installed only after the owner exists. nginx validation
precedes a graceful reload. Request logging is disabled for this vhost because
upstream websocket/SSE URLs contain JWTs. The owner username/password are written
only to root0600 `/srv/review/secrets/console-owner.json` and are never logged.

DNS/TLS preparation uses an isolated ACME home and the existing private managed
Cloudflare token; it refuses hostname conflicts and preserves unrelated records.
An isolated renewal timer retains the certificate. Review runtime, controller,
eight workers, DeepSeek, old management, the active manager unit, launcher,
fixed CLI and existing CODEX_HOME contents are excluded from the switch set.

After publication, perform browser HTTPS/login, streaming/tool/sudo, new/resumed
identity, worker-cwd identity, history reconnect and bounded-disconnect checks.
An open port, CLI-only smoke or model label alone does not complete acceptance.

Rollback: launch the installed release's `deploy/cn25/rollback.py` in a separate
root systemd unit. It checks ownership of the published vhost, removes only that
vhost with nginx validation/reload, and disables/stops only the two console units.
It preserves credentials, SQLite state, native history, artifact, DNS/TLS recovery
material and every manager/review service. No queue/history snapshot is restored.

## Existing-console upgrade: ingress and forward ownership

Rev acceptance uses `https://cn25.foliodude.it.com:2096`, after verifying that
2096 is not configured or listening on the VPS. Cloudflare's ordinary HTTPS
proxy supports 443, 2053, 2083, 2087, 2096 and 8443; it does **not** support 8444.
See https://developers.cloudflare.com/fundamentals/reference/network-ports/ .
Keep the primary 8443 upstream unchanged while existing runs drain. Validate
public TLS, owner login, the existing native steer history and a stable
WebSocket on the acceptance port before changing only the primary upstream.
Use an independent systemd update unit, preserve the active console/manager
processes, and retain a config backup with nginx validation and graceful reload.
Do not rerun the first-consumer installer against an existing deployment.

`cn25-console-forward.service` replaces the two competing tunnel supervisors.
It owns **both** remote loopback forwards (13301 to local3301 and13302 to3302)
in one SSH connection. Install `forward-client.py` as a root-owned0600 file in
`/srv/review/controller/cloudcli-forward-20261115/`, and `forward-lease.py` as
root-owned0600 `/etc/cn25-console/forward-lease.py` on the VPS. The existing SSH
configuration supplies authentication; neither helper reads or logs credentials.
Disable and stop only the two old forward units before transferring ownership.
Inspect exact existing listeners before the initial takeover; unknown owners
are preserved rather than killed. Keep all application services running.

The client takes a local exclusive lock and sends a heartbeat every10 seconds.
The server takes another exclusive lock, checks that the forwarding sshd is its
own ancestor and owns only the dedicated pair, and expires the lease after40
seconds without a heartbeat or immediately on EOF. Reclamation validates the
PID's start time and exact listening ports again; it cannot target the sshd
listener or an unrelated SSH session. The client deadline is45 seconds and
systemd retries after50 seconds, allowing remote expiry before reconnection.
No global sshd policy, shared credentials, application history or worker
configuration is changed. Status files contain only lifecycle metadata.

Run the failure-boundary tests with Python3.9 or newer:

```
python3 -m unittest discover -s deploy/cn25/tests -p 'test_*.py'
```

For a production acceptance, separately verify that missing heartbeats release
isolated test forward ports while the production owner stays unchanged. Retain
failed attempts and check unknown remote outcomes before retrying mutations.
