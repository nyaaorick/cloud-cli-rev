#!/bin/sh
set -eu
exec node "$(dirname "$0")/scripts/release/publish-rev-release.mjs" "$@"
