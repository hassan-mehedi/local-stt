#!/usr/bin/env bash
# Builds dist/local-stt-<version>.dmg: the menu bar app with its Python
# runtime, packages pinned to uv.lock, and the prebuilt system audio helper.
# Needs uv and the Xcode command line tools.
set -euo pipefail
cd "$(dirname "$0")/../.."

briefcase() { uvx --python 3.12 briefcase "$@"; }

swiftc -O -swift-version 5 \
    src/local_stt/audio/macos/system_audio_capture.swift \
    -o src/local_stt/audio/macos/system-audio-capture

# Briefcase installs with pip; the constraints pin every package to uv.lock
constraints="$(mktemp -t local-stt-constraints)"
trap 'rm -f "$constraints"' EXIT
uv export --frozen --no-dev --no-hashes --no-emit-project --no-header --no-annotate > "$constraints"
export PIP_CONSTRAINT="$constraints"

if [ -d build/local-stt/macos/app ]; then
    briefcase update macOS app --update-requirements --update-resources --no-input
else
    briefcase create macOS app --no-input
fi
briefcase package macOS app --update --adhoc-sign --packaging-format dmg --no-input
ls -lh dist/*.dmg
