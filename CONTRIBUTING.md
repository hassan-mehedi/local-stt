# Contributing to local-stt

This page gets you from a fresh clone to a tested change. The rules every change follows are in [CLAUDE.md](CLAUDE.md). Read it before your first pull request; it is short.

## How the pieces fit

local-stt has two halves that talk over HTTP on `127.0.0.1`:

- **The engine** (`src/local_stt/`, Python) does all the audio and speech work: the hotkey, the microphone, the speech models, typing the text, meetings, history. `stt engine` starts it with no window and prints its port and token.
- **The app** (`app/`, Tauri with React) is the window, the recording pill and the menu bar icon. It starts the engine as a child process and calls its HTTP API (`src/local_stt/ui/server.py` and `ui/app_api.py`).

A dictation goes like this: `dictation/listeners.py` sees the shortcut, `audio/capture.py` records, `engine/` turns the audio into text, `cleanup/` optionally rewrites it, the dictionary in `store.py` fixes spellings, `dictation/output.py` types it, and `store.py` saves it to history.

On Linux there is no Tauri app. `stt tray` runs the same engine with a GTK tray icon and a browser settings page (`ui/static/`).

## Set up

You need [uv](https://docs.astral.sh/uv/). For the Mac app you also need [pnpm](https://pnpm.io), [Rust](https://rustup.rs) and the Xcode command line tools.

```bash
git clone https://github.com/hassan-mehedi/local-stt.git
cd local-stt
uv sync                     # Python 3.11+, the engine and pytest
pnpm -C app install         # the app, macOS only
uv run stt models download parakeet-tdt-0.6b-v2   # or large-v3-turbo on Linux
```

## Run it

```bash
pnpm -C app tauri dev       # the Mac app; it runs the engine with `uv run stt engine`
uv run stt dictate          # the engine alone, in the terminal, no window
uv run stt tray             # Linux tray, or the older Mac menu bar app
```

In dev, macOS gives the permissions to your terminal app, not to local-stt. Turn on Microphone, Input Monitoring and Accessibility for the terminal, then restart the dev app.

The app, in dev and installed, writes the engine's log to `~/Library/Logs/io.github.hassan-mehedi.local-stt/engine.log`. `stt dictate` and `stt tray` log to the terminal.

## Check a change

There is no CI, so run all three before you open a pull request:

```bash
uv run pytest -q                  # Python tests
uvx ruff check .                  # lint; the rules are in pyproject.toml
pnpm -C app exec tsc --noEmit     # type-check the app
```

For a change to the app's screens, open them in a browser and check them by hand or with Playwright. `pnpm -C app dev` serves the UI on `http://localhost:1420`. Point it at a running engine with `?port=<port>&token=<token>` from the engine's first output line.

To try the engine without touching your own settings and history, give it a separate home folder:

```bash
HOME=/tmp/stt-home PYTHON_KEYRING_BACKEND=keyring.backends.null.Keyring uv run stt engine
```

The keyring line matters on a Mac. Without it, the engine looks for a Keychain in the fake home and macOS shows a "Keychain Not Found" dialog.

## Build the app

```bash
./packaging/macos/build.sh        # dist/local-stt-<version>.dmg
```

To change the version, run `packaging/set_version.sh 0.3.0`. The version is kept in five files and two lockfiles, and `build.sh` stops if they disagree.

The script bundles a standalone Python with the packages pinned in `uv.lock`, builds the Tauri app and signs it. Sign with a self-signed "local-stt Dev" certificate (see the [user guide](docs/user-guide.md#install)). macOS keeps the app's permissions across rebuilds only when the signature stays the same.

## Where things go

- New code goes in the feature folder it belongs to: `audio/`, `cleanup/`, `dictation/`, `engine/`, `meeting/` or `ui/`.
- Settings live in `config.py` and `~/.config/local-stt/config.toml`.
- History and the dictionary live in one SQLite file, managed by `store.py`.
- Tests are flat in `tests/`, one `test_<module>.py` per module. Fake the microphone, the model and the network; tests never touch real ones.

CLAUDE.md has the full list, plus the rules for comments, tests and HTTP routes.
