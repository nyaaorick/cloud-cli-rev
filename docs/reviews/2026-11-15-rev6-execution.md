# SDD ledger — plan: docs/plans/2026-11-15-rev6-workbench.md

Base: 5eace2ee3c65bdf03d3b9bbdd823a753f96476d3.
User: central Codex chat; files/editor on demand; VS Code visual and interaction model.
Design builder check: nothing important left (rev6_design_check).
Pre-flight: Task 1 produces workspace context/chrome semantic classes; Task 2 consumes these with theme tokens; no conflict. Task 3 changes metadata only.
Path: rewrite app → Shortest: reuse existing modules; replace chrome, layout and theme.

Task 1: implemented — terminal/palette/context/chrome and sidebar toggle tests RED→GREEN; chat DOM retention verified in Chrome.
Task 2: implemented — Modern theme, compact navigation and sidebar explorer; desktop/mobile and light/dark screenshots verified.
Task 3: metadata prepared; 155 frontend files / 1140 tests PASS. Final type/lint/build and independent review pending.
Execution adjustment: Tasks 1/2 share layout/theme files and are committed as one coherent candidate for whole-branch review; no intermediate integrations.
Backend check: 1022 pass, 3 fail, 4 skip; no backend changes. Codex notification failure reproduced on rev5. Other failures recorded, not hidden.
Evidence: docs/journal/2026-11-15-rev6-workbench.md; full local logs in workspace .claude/scratchpad/cloud-cli-rev6/.
Task 3 verification: typecheck, lint, full build exit 0; palette dependency follow-up targeted 9/9 PASS. Local candidate commit follows; review pending.

Final review: independent rev6_implementation_review on 5eace2ee..14bde1fd; Critical 0, Important 2, Minor 1.
Final: fixed hidden terminal auto-connect — workbenchTerminalRuntime production runtime/socket test RED→GREEN; real xterm Chrome replay confirms.
Final: fixed activity-bar clipping — 1100×500 / 5 plugins Chrome RED→GREEN; navigation scrolls and fixed bottom actions remain reachable.
Final: Ctrl+J regraded Important by effect (could submit a terminal command); fixed capture handling — terminal consumer test RED→GREEN; Chrome input frames empty.
Final: Ruling: release/deployment/real CLI behavior unjudged by reviewer — local UI candidate only — cost if wrong: real service validation still required.
Final: Ruling: backend failures outside UI diff — preserve results without unrelated changes — cost if wrong: release could retain backend defects; no full release PASS claim.
Final: Ruling: editor minimum chat width of 200px is baseline behavior — retain it — cost if wrong: extreme narrow chat still has crowded controls.
Final minors: none deferred (Ctrl+J upgraded and fixed).
Final full checks pending after fixes; report preserved in docs/reviews/2026-11-15-rev6-workbench.md.

Final: fixed all 3 regraded Important findings; final suite 156 files / 1142 tests PASS, typecheck/lint/build exit 0. Chrome confirms settings + every plugin reachable and Ctrl+J sends no input.
Task 3: complete as local UI candidate; source version rev6 prepared, no push/tag/release/deployment. Backend limitations remain explicit.
Delivery: retain feat/vscode-codex-workbench and its worktree under the authorized local-only scope. No integration menu needed for this handoff; no merge or publication performed.
