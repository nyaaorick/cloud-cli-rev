# Contributing to Cloud Cli rev

Cloud Cli rev is an independently maintained derivative of CloudCLI UI
(https://github.com/siteboon/claudecodeui). Use this repository's issues and pull
requests for changes to this derivative. The original contribution guide is
retained as [CONTRIBUTING.upstream.md](CONTRIBUTING.upstream.md).

Use Node.js 22 or later, install the locked dependencies with `npm ci`, and follow
the module instructions in [AGENTS.md](AGENTS.md). Keep changes on a focused
branch and use Conventional Commits. Run the relevant tests, typecheck, build
and lint before submitting a pull request. Explain the resulting behavior and
record actual validation, including any failures or skipped checks.

Preserve the upstream Git history, [LICENSE](LICENSE), [NOTICE](NOTICE),
attribution and additional terms. Contributions remain under
AGPL-3.0-or-later. Do not commit credentials, environment files, account data,
databases, private logs or native session transcripts.

Publishing source does not deploy a service. Runtime changes require their own
reviewed build and deployment procedure, preserving existing histories and
unrelated services. The historical upstream release/notification workflows are
kept outside `.github/workflows/`; npm publishing is disabled for this repository.
