# Cloud Cli rev GitHub releases and fixed-service updates

The only update source is https://github.com/nyaaorick/cloud-cli-rev/releases.
The browser, authenticated API and CLI use the same complete SemVer comparison.
A Git tag alone is not a release. Neither update path installs upstream npm packages.

Commit tested source and the version/lockfile, tag that commit as
`vMAJOR.MINOR.PATCH-rev.N`, then push it. The GitHub workflow runs backend/frontend
checks, Python deployment tests, types, lint and build before publishing the app
archive, `release-manifest.json` and `SHA256SUMS` as the latest release.
`npm run release:bundle` and `npm run release` perform the same packaging and
publication locally. Publication refuses a dirty source tree, mismatched tag,
commit or an existing release. Use a single publisher. Credentials and `.env`
files are never included or read by these scripts.

The archive retains AGPL LICENSE/NOTICE and an immutable source URL. It excludes
homes, databases, authentication state and node_modules. Its runtime package
omits development/Git lifecycle hooks; native dependency install scripts and
the node-pty runtime fix remain enabled. Install with Node22 and
`npm ci --omit=dev`, or reuse an existing Node22 dependency tree only after the
complete lock fingerprint matches. HTTPS and GitHub repository permissions are
the trust boundary; checksums detect corruption, not a compromised publisher.

CN25 uses one external Python3.9 script, run by the root oneshot
`cn25-cloudcli-rev-update.service`, outside the console's cgroup:

1. Download the latest Rev release; verify repository, version/tag, archive,
   manifest, checksums, lockfile, LICENSE/NOTICE and safe archive paths/types.
2. Prepare a new immutable version directory and managed-install marker.
3. Wait for running sessions, background work, protected PID birth identities
   and **all descendants** of the existing console to clear for 30 seconds.
   An idle Shell/CLI process also blocks the update; it is never killed just
   to finish an update. An unknown status/auth error fails closed.
4. Recheck idle state, change only the fixed service's ExecStart override,
   and restart **cn25-console-rev.service**, retaining port3302, home, state,
   existing environment-file references, shared tunnel and public8443 URL.
5. Verify local managed-version health and the same public HTTPS URL. Atomically
   update the active receipt and `rev-current` link. Keep the previous version.
   On failed health, restore the exact previous override and restart that version.

No per-version app units, extra ports, new tunnels or Nginx changes are created.
The idle checks are conservative polling; they do not reserve an atomic
application admission lock. Run the switch during a quiet window. Any shell or
CLI that remains open postpones it, including the manager requesting the update.
The update API reports **queued**, never falsely reports an installed version.
An update may remain waiting until that CLI exits after its final answer.

Rev 9 bundles Codex 0.170.0 and lists GPT-6.2 Astra and Sol. CN25 manager
mode uses the separate root-owned executable set by `CN25_MANAGER_CODEX_PATH`.
Before activating the app, stage the verified Linux Codex 0.170.0 toolchain in
a new immutable directory and confirm both slugs in `codex debug models --bundled`.
At the guarded idle cutover, point the Rev unit's manager CLI and toolchain
`PATH` at that directory. Preserve the previous override and executable for
rollback. Confirm a native Bifrost turn using each model and read back the actual
model from the turn. A catalog entry alone does not verify gateway access.

The root-owned controller and nonsecret `config.json` live under
`/srv/review/controller/cloudcli-rev-updates/`. Configuration names the canonical
repository, absolute Node/npm paths, releases directory, fixed service/port,
public URL, owner credential **path**, initial version/release, optional protected
`{pid,start}` identities and wait/quiet limits. Owner authentication is used only
against loopback; password/token values remain in memory and never enter argv,
logs or receipts. Unit timeout must exceed the idle wait plus installation time.
The app/CLI can queue only the fixed update unit named by its root-owned marker.
Unmanaged source/archive installs show the GitHub release link instead.

Each tag attempt retains `deployment.json`, the verified manifest and archive.
`active.json`, `previous.json` and `last-result.json` record activation/rollback.
Do not delete an attempt to force a retry or replay an unknown result. Inspect
its exact service override and health first. The updater never replaces itself
from downloaded code; controller changes are installed separately for review.
No worker, queue, history, database or credential file is in the rollback set.

Rev7 also publishes a separate pinned Cloudflare offline environment and
`CLOUDFLARE-SHA256SUMS`; its assets do not change the updater's two-entry app
checksum format. See [Cloudflare maintenance](cloudflare/README.md). On CN25,
post-activation completion verifies the new version, adopts the matching
existing tunnel environment without restarting it, verifies the local
diagnostics and physical browser, and then removes only explicitly proven duplicate
artifacts. Failed/unknown attempts remain intact. Existing CLI descendants keep
the update waiting; the requesting manager is never killed to finish it.
