# Rev7 Cloudflare environment and startup maintenance

Based on immutable Rev6 `e00c8aca510032af670230f749589467b90815ae`.
The workbench, native steering, fixed updater and all existing application
behavior are retained.

Changes:

- Add `deploy/cn25/cloudflare` with validated nonsecret configuration, pinned
  official binary metadata/license, offline environment packaging, credential
  file handoff, physical routing, exact owned-rule maintenance and diagnostics.
- Persist the dedicated UID/GID with systemd-sysusers. The live connector can
  outlive a missing NSS account mapping; process liveness alone does not prove
  that the next service start will succeed.
- Remove the Google Fonts preconnect/stylesheet links from source. Earlier
  deployed-HTML overlays did not survive the Rev6 rebuild.
- Recognize and remove only the two proven redundant old HTTPS rules and the
  exact physical drop-in now represented in the generated base unit.
- Publish the environment as a separate optional asset, preserving the app
  updater's two-entry checksum format and the existing single CI publisher.

Local validation:

- Backend: 1029 passed, 1 skipped, no failures/cancellations.
- Frontend: 1142 passed. The first local command incorrectly supplied manager
  build mode to generic tests, causing seven default-provider expectation
  failures; the original log is retained and the corrected CI-mode run passes.
- Existing deployment tests: 18 passed; new environment tests: 23 passed.
- Typecheck, lint and manager-mode application build pass.
- Disposable-network integration passes real nft deduplication/idempotency,
  injected post-write rollback, unrelated-forward preservation, route collision
  checks and no-TUN-fallback checks. The script refuses the host net namespace.
- Generated systemd units and sysusers dry-run validate successfully.
- Real Chromium loads the new built login page with all external networking
  blocked, makes zero Google Fonts requests and uses the existing system-font
  CSS stack. This is a startup check, separate from production activation.

GitHub release CI and independent post-activation receipts establish publication
and runtime state separately. An active manager/CLI keeps the fixed updater
waiting; it is not terminated to complete deployment. Post-activation checks
use existing authenticated history and a120-second physical WebSocket, without
sending a new chat task. Generated-file cleanup follows successful acceptance;
credentials, databases, historical attempts, queues, previous runtime and
shared dependencies are preserved. No independent model review was run for
this maintenance change; the separate CI environment and live checks are the
independent verification boundaries.
