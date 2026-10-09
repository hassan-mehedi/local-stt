#!/usr/bin/env bash
# Builds dist/local-stt-<version>.dmg: the Tauri app (app/) with the Python
# engine inside it at Contents/Resources/engine, packages pinned to uv.lock,
# and the prebuilt system audio helper.
#
# Needs uv, pnpm, Rust and the Xcode command line tools. Signs with the
# "local-stt Dev" identity from the login keychain when it is there, else
# SIGN_IDENTITY, else ad hoc. macOS hands Accessibility to the engine only
# under a stable identity, and keeps privacy grants across rebuilds only then.
set -euo pipefail
cd "$(dirname "$0")/../.."
root=$PWD
engine=app/src-tauri/engine
python=3.12
version=$(sed -n 's/^version = "\(.*\)"/\1/p' pyproject.toml | head -1)
for f in src/local_stt/__init__.py app/package.json app/src-tauri/Cargo.toml app/src-tauri/tauri.conf.json; do
    grep -q "\"$version\"" "$f" || { echo "error: $f is not at version $version; run packaging/set_version.sh $version" >&2; exit 1; }
done

tmp=$(mktemp -d -t local-stt-build)
trap 'rm -rf "$tmp"' EXIT

echo "== system audio helper"
swiftc -O -swift-version 5 \
    src/local_stt/audio/macos/system_audio_capture.swift \
    -o src/local_stt/audio/macos/system-audio-capture

echo "== Python $python runtime"
find "$engine" -mindepth 1 -maxdepth 1 ! -name .gitkeep -exec rm -rf {} +
UV_PYTHON_INSTALL_DIR="$tmp/python" uv python install "$python" --no-bin
runtime=$(find "$tmp/python" -maxdepth 1 -name "cpython-$python*" -type d | head -1)
cp -R "$runtime" "$engine/python"
py="$engine/python/bin/python$python"

echo "== engine packages"
uv export --frozen --no-dev --no-hashes --no-emit-project --no-header --no-annotate > "$tmp/requirements.txt"
uv build --wheel --out-dir "$tmp/wheel" >/dev/null
uv pip install --python "$py" --break-system-packages --link-mode copy -r "$tmp/requirements.txt"
uv pip install --python "$py" --break-system-packages --link-mode copy --no-deps "$tmp"/wheel/*.whl
site=$("$py" -c 'import sysconfig; print(sysconfig.get_paths()["purelib"])')
# the wheel leaves out files git ignores, the helper among them
cp src/local_stt/audio/macos/system-audio-capture "$site/local_stt/audio/macos/"

echo "== trim and precompile"
lib="$engine/python/lib/python$python"
rm -rf "$lib/test" "$lib/idlelib" "$lib/tkinter" "$lib/turtledemo" "$lib/ensurepip" \
    "$engine/python/lib/tcl"* "$engine/python/lib/tk"* "$engine/python/share"
find "$engine/python" -name __pycache__ -type d -prune -exec rm -rf {} +
# unchecked: the copy into the bundle changes file times, which would make
# Python ignore these and compile in memory on every start. The app runs it
# with -B, since a written .pyc would break the bundle's signature.
"$py" -m compileall -q -j 0 --invalidation-mode unchecked-hash "$engine/python/lib" || true

echo "== app"
identity=${SIGN_IDENTITY:-$(security find-identity -p codesigning 2>/dev/null \
    | sed -n 's/.*) \([0-9A-F]\{40\}\) "local-stt Dev".*/\1/p' | head -1)}
if [ -z "$identity" ]; then
    identity="-"
    echo "warning: no \"local-stt Dev\" identity; signing ad hoc, so Accessibility will not reach the engine" >&2
fi
export APPLE_SIGNING_IDENTITY="$identity"
case "$(ld -v 2>&1)" in
    *ld-27037*)
        # see packaging/macos/ldfix/cc-wrapper.sh
        export CARGO_TARGET_AARCH64_APPLE_DARWIN_LINKER="$root/packaging/macos/ldfix/cc-wrapper.sh"
        export CARGO_PROFILE_RELEASE_STRIP=none CARGO_PROFILE_RELEASE_BUILD_OVERRIDE_STRIP=none
        ;;
esac
(cd app && pnpm install --frozen-lockfile && pnpm tauri build --bundles app)

echo "== dmg"
app_path=app/src-tauri/target/release/bundle/macos/local-stt.app
codesign --verify --deep --strict "$app_path"
mkdir -p dist "$tmp/dmg"
cp -R "$app_path" "$tmp/dmg/"
ln -s /Applications "$tmp/dmg/Applications"
dmg="dist/local-stt-$version.dmg"
rm -f "$dmg"
hdiutil create -quiet -volname local-stt -srcfolder "$tmp/dmg" -format UDZO "$dmg"

# the DMG holds the app; left behind, these copies show up in Spotlight
# next to the installed app
rm -rf "$app_path" "$engine/python" app/src-tauri/target/release/engine
ls -lh "$dmg"
