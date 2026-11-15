# Cloud Cli rev GitHub releases and managed updates

The only update channel is `nyaaorick/cloud-cli-rev` on GitHub. Neither the
browser nor `cloud-cli-rev update` installs the original CloudCLI npm package.
The Rev maintenance channel uses `MAJOR.MINOR.PATCH-rev.N` package versions,
matching `vMAJOR.MINOR.PATCH-rev.N` Git tags, and GitHub Releases marked **latest**
and **not prerelease**. The suffix identifies this fork's maintenance series;
SemVer precedence still applies, including numeric identifiers and build data.
A tag alone does not appear in GitHub's latest-release API.

After tests, typecheck, lint and a build, commit the version and lockfile changes,
tag that exact commit, and push the commit and tag. `Rev GitHub Release` builds
the immutable tag and publishes the application archive, `release-manifest.json`
and `SHA256SUMS`. `npm run release:bundle` builds those same files locally;
`npm run release` publishes an already tested, committed and tagged bundle with
`gh`. The publisher never reads `.env`, publishes to npm or sends notifications.
Run local tests without inheriting service-specific provider paths; the GitHub runner provides a clean test environment. Backend test concurrency is bounded to avoid timer starvation. Use one publisher for a tag; it refuses to overwrite an existing release.

The archive contains built browser/server files, runtime source, deploy helpers,
the license and a dependency lockfile. It excludes authentication state, homes,
databases and node_modules. Install production dependencies with Node22 on the
target host, or reuse an immutable dependency tree only when the complete lock
fingerprint matches. Native modules must match the target Node ABI. Manifest
checksums verify downloaded bytes; GitHub HTTPS and repository permissions are
the trust boundary. Source for AGPL compliance is linked by immutable commit.

CN25 uses a root-owned deployment controller, independent of every running
console and manager CLI:

- Controller: `/srv/review/controller/cloudcli-rev-updates/rev-update.py`.
- Nonsecret root0600 configuration: the same directory's `config.json`.
- Update unit: `cn25-cloudcli-rev-update.service`; Type=oneshot, root, 30-minute
  timeout, with the existing Node22 directory in PATH and no credential output.
- The root-owned `.rev-install.json` in a managed release names only that fixed
  unit. HTTP/CLI callers cannot provide a shell command, repository or unit name.
- The browser's Update and `cloud-cli-rev update` queue that unit. An up-to-date
  install returns success without starting it. Source checkouts and archives
  show the GitHub release link; they cannot silently invoke an npm updater.
- The dedicated `/usr/local/bin/cloud-cli-rev` launcher follows the atomically
  activated `rev-current` link. App services always use immutable release paths;
  changing this launcher never replaces a running Codex CLI or its home.

The controller validates repository, tag, version, manifest, SHA256, lockfile,
archive paths and file types. It refuses downgrades, path traversal, links,
occupied ports, an existing unrecorded deployment and unknown remote outcomes.
After a successful activation it atomically installs the controller from that
same verified release for the next update, after a Python syntax preflight.
It serializes deployments, installs into a new version directory, creates a new
app unit and a new independently leased SSH forward, then checks public HTTPS
on2053 before switching only the primary8443 Nginx upstream with validation and
graceful reload. Existing app/CLI/home units and their SSH forwards remain alive.
The original pair13301/13302 is never restarted or reclaimed by this controller.

Configuration includes repository, releases directory, absolute node/npmCLI
paths, the existing app unit used as a template, existing SSH configuration path,
hostname, and an `initial` object with version/release/port/forward_port and the
exact current primary Nginx SHA256. Later updates use root0600 `active.json`.
Private SSH config is consumed only by SSH itself; the controller never reads it.
The existing app EnvironmentFile reference is retained without reading its file.

Every deployment stores durable intent and remote systemd receipts by tag.
If transport is lost during a remote mutation, inspect those exact receipts and
Nginx hashes before taking another action. Do not delete an attempt directory
to force a retry. Older app instances are intentionally retained for live turns;
retirement is separate authorized work. No worker, queue, history or credential
file belongs to the update or rollback set.

Rollback changes only the primary Nginx upstream to the prior preserved instance,
after comparing the current hash with the deployment receipt and checking the
old app/forward. Use another independent systemd unit, retain a config backup,
run `nginx -t` and reload gracefully. Preserve the failed release, logs, remote
receipt, credentials and state; never restore a database snapshot over live work.
