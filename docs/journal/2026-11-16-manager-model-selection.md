# Manager model and reasoning selection

Owner request: "思考深度选项和模型选项完全解锁".

The manager profile previously filtered the catalog to Sol/xhigh and replaced selections during main and side-question runs. Keep the existing fixed CLI, Bifrost authentication, administrator instructions and permission settings, while exposing the complete supported catalog and carrying the selected model/effort into new and resumed turns. Configured defaults remain defaults.

The regression was reproduced before implementation: both manager catalog/runtime cases failed on missing choices, and the side-question JSON-RPC fixture received Sol when Terra was requested. The corrected focused suite passed 42 tests. The manager capability endpoint also retained an xhigh-only restriction; its new regression failed before that final restriction was removed.

Validation:

- Backend full suite: 1027 passed, 4 skipped, no failures (1031 tests).
- Frontend full suite: 1142 passed. The first simultaneous full-check run hit the existing `authTokenRefreshRemount` timing assertion; its isolated run and the subsequent complete frontend run passed. Original logs are retained.
- Deployment tests: 18 existing updater tests and 23 Cloudflare environment tests passed.
- Typecheck, lint and the manager-mode application build passed. Existing lint/build warnings remain outside this focused change.
- Actual manager CLI inference through Bifrost completed successfully with Terra and Astra, using low effort and a bounded no-tool prompt.
- Independent review, GitHub release CI and post-update browser/native-session evidence are separate delivery checks.

Independent review of the first snapshot found `UNLOCK-B1`: persistent branch/edit forks still sent the configured manager default. The RPC regression failed with Sol in that field; the follow-up removes the override so the native fork inherits its parent model. The affected fork/edit/manager/capability checks passed (38 passed, one unavailable native fixture skipped), and typecheck/server build passed again. The original finding and focused follow-up review are retained in the delivery evidence.

The fix builds on rev.7, including its Cloudflare environment and startup-font changes. It does not migrate the review-machine runtime or alter its queue, workers or publishing policy.
