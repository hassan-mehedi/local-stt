#!/usr/bin/env bash
# Sets the version everywhere it is kept: pyproject.toml, the Python package,
# the app's package.json, Cargo.toml, tauri.conf.json and the lockfiles.
# Usage: packaging/set_version.sh 0.3.0
set -euo pipefail
cd "$(dirname "$0")/.."
new=${1:?usage: packaging/set_version.sh 0.3.0}
[[ $new =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || { echo "not a version: $new" >&2; exit 1; }

# only the package's own version line, near the top of each file
perl -pi -e 's/^version = ".*"/version = "'"$new"'"/ if $. < 10; close ARGV if eof' pyproject.toml app/src-tauri/Cargo.toml
perl -pi -e 's/^__version__ = ".*"/__version__ = "'"$new"'"/' src/local_stt/__init__.py
perl -pi -e 's/^  "version": ".*",/  "version": "'"$new"'",/' app/package.json app/src-tauri/tauri.conf.json
uv lock --quiet
(cd app/src-tauri && cargo update --quiet --offline --workspace)
echo "version set to $new"
