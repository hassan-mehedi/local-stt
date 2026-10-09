# local-stt

Local, offline speech-to-text for Linux and macOS (Apple Silicon). Press a hotkey, speak, press again, and the text appears in whatever app has focus. Also transcribes audio/video files and records meetings (your mic + the other side) with speaker labels. Speech recognition runs on your machine: no account, no telemetry. The one exception is the optional cleanup, which sends the text (never the audio) to an AI API you pick.

Using the Mac app? Read the [user guide](docs/user-guide.md). Want to change the code? Start with [CONTRIBUTING.md](CONTRIBUTING.md).

- **Dictation**: global hotkey toggles recording; transcribes and types into the focused window.
- **File transcription**: any audio/video → `txt` / `md` / `srt` / `vtt` / `json`.
- **Meetings**: records mic ("Me") and system audio ("Them") as separate tracks, transcribes and merges them. Optional speaker diarization.
- **Tray app**: status icon + menu, with a browser-based settings page (switch models, rebind the hotkey, manage downloads).
- **Cleanup** (Mac app, optional): an AI model through an API such as DeepSeek or OpenAI removes filler words and fixes punctuation. The API key stays in the Keychain.

Powered by [faster-whisper](https://github.com/SYSTRAN/faster-whisper) (CTranslate2), which uses your NVIDIA GPU if present and falls back to CPU. On Apple Silicon the default is NVIDIA Parakeet via [parakeet-mlx](https://github.com/senstella/parakeet-mlx), which runs on the Mac's GPU.

On a Mac, skip to [macOS](#macos-apple-silicon); the sections before it are for Linux.

---

## Requirements

- **Linux on X11.** Tested on Linux Mint / Cinnamon. (Wayland support exists but is unverified; see [below](#wayland).)
- **Python 3.11+**
- **NVIDIA GPU (optional but recommended).** Needs a recent proprietary driver. Without one it runs on the CPU, which is fine for file transcription and slow for dictation. No CUDA toolkit needed; the CUDA libraries install via pip.
- **[uv](https://docs.astral.sh/uv/)**, the Python project manager and installer used here:
  ```bash
  curl -LsSf https://astral.sh/uv/install.sh | sh
  ```

### System packages

```bash
sudo apt install ffmpeg xdotool xclip libnotify-bin pipewire-bin \
                 python3-gi gir1.2-gtk-3.0 gir1.2-ayatanaappindicator3-0.1
```

| Package | Used for |
|---|---|
| `ffmpeg` | decoding audio/video files |
| `xdotool` | typing text into the focused window (X11) |
| `xclip` | clipboard output mode (X11) |
| `libnotify-bin` | desktop notifications (`notify-send`) |
| `pipewire-bin` | meeting recording (`pw-record`) |
| `python3-gi`, `gir1.2-gtk-3.0`, `gir1.2-ayatanaappindicator3-0.1` | the tray icon (system PyGObject + Ayatana AppIndicator) |

> The tray uses your **system** PyGObject, not a pip package. These GObject-introspection packages are required for the tray icon to appear. On Mint they're usually preinstalled.

---

## Install

```bash
git clone <repo-url> local-stt
cd local-stt

# Install the `stt` command globally (drop `cuda` if you have no NVIDIA GPU):
uv tool install --editable '.[cuda]' --overrides overrides.txt

# Download the default model (~1.6 GB):
stt models download large-v3-turbo
```

`stt` is now on your PATH. (The `--overrides overrides.txt` flag skips an optional Linux build dependency that's only needed for Wayland; see [below](#wayland).)

> Prefer not to install globally? Use `uv sync --extra cuda` and prefix every command with `uv run` (e.g. `uv run stt dictate`).

### Start the tray (recommended)

```bash
stt tray
```

A microphone icon appears in your panel. Dictation starts automatically. Click the icon for the menu (start/stop dictation, record a meeting, settings, quit). The icon shows state: dimmed = off, green = listening, red = recording, amber = transcribing.

### Run in the background (systemd user service)

The repo ships a unit at [`packaging/local-stt.service`](packaging/local-stt.service). Install it to start the tray on every login and restart it if it ever crashes:

```bash
mkdir -p ~/.config/systemd/user
cp packaging/local-stt.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now local-stt.service     # start now + on every login
```

Manage and inspect it:

```bash
systemctl --user status local-stt.service
systemctl --user restart local-stt.service          # after upgrading the tool
systemctl --user stop local-stt.service
journalctl --user -u local-stt -f                    # follow the logs
```

The unit sets `Environment=DISPLAY=:0` and installs into `default.target` (Cinnamon doesn't reliably activate `graphical-session.target` for the user manager). If your session uses a different display, edit `DISPLAY` in the unit.

Only one tray runs at a time: the service plus a manual `stt tray` won't double up (a second instance just exits).

> Prefer a desktop autostart entry instead? Create `~/.config/autostart/local-stt-tray.desktop` with `Exec=` pointing at `$(command -v stt) tray`. The systemd service is recommended (auto-restart + journald logs); don't enable both.

---

## macOS (Apple Silicon)

### Requirements

- **macOS 14.2 or later** on Apple Silicon (meeting capture uses Core Audio process taps, added in 14.2).
- **[uv](https://docs.astral.sh/uv/)**: `curl -LsSf https://astral.sh/uv/install.sh | sh`
- **Xcode command line tools**, for meetings only: `xcode-select --install`. The first meeting compiles a small Swift helper that records system audio; it is cached in `~/.cache/local-stt/bin/`.
- **ffmpeg**, only for `stt file` on formats other than 16-bit WAV: `brew install ffmpeg`.

### Install the app

Build the DMG once. It needs uv, [pnpm](https://pnpm.io), [Rust](https://rustup.rs) and the Xcode command line tools, and takes about 5 minutes:

```bash
./packaging/macos/build.sh    # writes dist/local-stt-<version>.dmg
```

Open the DMG and drag local-stt into Applications. On first launch a setup window walks you through the model download, the microphone, the two keyboard permissions and a test dictation. The app is a Tauri window around the same engine (`stt engine`), which runs inside the bundle.

While you dictate, a pill at the bottom of the screen shows the mic level; X or Esc throws the clip away. Home keeps every dictation with its recording until you delete it, Meetings plays and searches transcripts, Insights counts words, and Dictionary fixes spellings and expands phrases. Settings > Cleanup sets up the optional AI cleanup; the [user guide](docs/user-guide.md#clean-up-what-you-said) walks through it.

**Signing.** There is no Apple developer certificate, so `build.sh` signs with a self-signed identity named "local-stt Dev" from your login keychain if there is one, and ad hoc otherwise. Use the self-signed identity: macOS only passes the Accessibility permission on to the engine, and only keeps permissions across rebuilds, when the signature stays the same. Create it in Keychain Access (Certificate Assistant > Create a Certificate, type Code Signing) or with openssl. On another Mac, right-click the app and pick **Open** the first time.

The app has no `stt` command and can't convert `bengali-whisper-medium` (that needs torch). Use the source install below for both; the app picks up models downloaded there.

### Install from source

```bash
uv tool install --editable .
stt models download parakeet-tdt-0.6b-v2    # the Mac default, ~2.5 GB, English
stt tray
```

A mic icon appears in the menu bar: slashed = off, plain = listening, red = recording, orange waveform = transcribing. Dictation starts on its own. The default hotkey is Option+Shift+T. The app keeps that keystroke from reaching the focused window, so it doesn't type "ˇ".

### Permissions

The setup window asks for the first three; System Audio Recording is under Settings > Permissions. Grant them to local-stt.app, or for a source install to the app that runs `stt`: your terminal when you run it by hand, or the Python binary named in the error message when it runs as a login agent. Restart local-stt after granting.

| Permission (System Settings > Privacy & Security) | Needed for |
|---|---|
| Input Monitoring | reading the hotkey |
| Accessibility | typing or pasting the text into the focused app |
| Microphone | dictation and the "Me" meeting track |
| Screen & System Audio Recording > System Audio Recording Only | the "Them" meeting track. Without it the track is silent and the log says so |

### Start at login

In the app, turn on Settings > General > Open at login. For a source install, use launchd:

```bash
mkdir -p ~/Library/LaunchAgents
sed "s|__HOME__|$HOME|g" packaging/local-stt.plist > ~/Library/LaunchAgents/local-stt.plist
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/local-stt.plist
```

Manage it:

```bash
launchctl kickstart -k gui/$(id -u)/local-stt     # restart, e.g. after an upgrade
launchctl bootout gui/$(id -u)/local-stt          # stop and remove from this login
tail -f ~/Library/Logs/local-stt.log
```

launchd restarts the app if it crashes, but not after you pick Quit from the menu.

---

## Usage

```bash
# Dictation: press Alt+Shift+T to start, press again to stop (default: toggle mode)
stt dictate

# Transcribe files
stt file recording.mp3 -o md,srt,json
stt file lecture.mp4 --language en --out-dir ~/transcripts

# Tray app (status icon + settings)
stt tray

# Settings page in your browser (model, hotkey, modes, downloads)
stt settings                              # or the tray's "Settings…" item

# Meetings: records mic (Me) + system audio (Them), transcribes on stop
stt meeting --name "weekly standup"
stt meeting stop                          # from another terminal, or just Ctrl+C
stt meeting transcribe <session-dir>      # (re)transcribe an existing recording
stt meeting --name "standup" --diarize    # split remote speakers (see below)
stt meeting --name "sync" --language bn   # a Bengali meeting (see below)

# Models
stt models list
stt models download medium
stt models remove medium
```

> **Tip:** for meetings, use headphones. On speakers, the other side's voice leaks into your mic and shows up under both "Me" and "Them".

---

## Settings UI

`stt settings` (or the tray's **Settings…** item) opens a local page served on `127.0.0.1` with a per-session token. No internet is involved. From it you can:

- switch the active model, and download/remove models;
- rebind the dictation hotkey by **pressing** the combo, or by tapping one modifier on its own (Right Option);
- change mode (toggle/hold), output (type/clipboard), language, and the meetings folder;
- set a Hugging Face token for diarization.

**Apply** restarts the dictation daemon in place, so changes take effect right away without a logout. Edits are written to `config.toml` with your comments preserved.

---

## Configuration

`~/.config/local-stt/config.toml` is created on first save; every key is optional and falls back to the defaults below.

```toml
[model]
name = "large-v3-turbo"       # Linux default; Apple Silicon defaults to parakeet-tdt-0.6b-v2
compute_type = "float16"      # try "int8_float16" if latency is poor or VRAM is tight
device = "auto"               # "auto" | "cuda" | "cpu"
language = "en"               # "" = auto-detect

[dictation]
hotkey = "<alt>+<shift>+t"    # or one modifier on one side: "alt_r", "cmd_r", "ctrl_l", ...
mode = "toggle"               # "toggle" (press start/stop) | "hold" (push-to-talk)
output = "type"               # "type" | "clipboard" (paste with Ctrl+V, Cmd+V on macOS)
listener = "auto"             # "auto" | "pynput" (X11) | "evdev" (Wayland)
min_duration_ms = 300         # ignore shorter recordings
max_duration_ms = 300000      # toggle-mode auto-stop after this long (0 = off)
append_space = true
notify = true

[meeting]
output_dir = "~/Documents/meetings"
model = ""                    # blank = the [model] name
language = ""                 # blank = the [model] language

[diarize]
hf_token = ""                 # Hugging Face token (or set HF_TOKEN); see below

[cleanup]                     # set up in the Mac app's Settings > Cleanup
enabled = false
api_url = ""                  # any OpenAI-compatible API, e.g. "https://api.deepseek.com"
api_model = ""                # e.g. "deepseek-flash"; the API key lives in the Keychain
```

---

## Models

All run offline once downloaded (cached in `~/.cache/local-stt/models/`). Pick with `stt models download <name>` and select in the settings page or `[model] name`.

| Model | Size | Notes |
|---|---|---|
| `large-v3-turbo` | ~1.6 GB | **Default on Linux.** Best quality/speed balance; great on a 6 GB+ GPU. |
| `large-v3` | ~3 GB | Highest quality, slower. |
| `distil-large-v3` | ~1.5 GB | Faster, English-leaning. |
| `medium` | ~1.5 GB | Good on smaller GPUs. |
| `small` / `base` / `tiny` | 484 / 145 / 75 MB | Lightweight; CPU-friendly, lower accuracy. |
| `parakeet-tdt-0.6b-v2` | ~2.5 GB | **Default on Apple Silicon.** NVIDIA Parakeet, English only. Apple Silicon only for now (runs on the GPU via [parakeet-mlx](https://github.com/senstella/parakeet-mlx)). |
| `parakeet-tdt-0.6b-v3` | ~2.5 GB | Parakeet for 25 European languages, detects the language itself. Apple Silicon only for now. |

Parakeet ignores `[model] language` (v3 picks the language on its own) and has no translate mode. Languages outside its list, such as Arabic or Hindi, need a Whisper model.

If a model won't fit in VRAM, set `compute_type = "int8_float16"` (or `"int8"`), or choose a smaller model.

---

## Bengali meetings

Parakeet has no Bengali. For Bengali meetings there is `bengali-whisper-medium`, a Whisper medium fine-tune from [Bengali.AI](https://huggingface.co/bengaliAI/tugstugi_bengaliai-asr_whisper-medium) (Apache 2.0). On hour-long Bengali recordings it scored 34.8% WER in the [ShobdoSetu paper](https://arxiv.org/pdf/2603.19256), against 75.0% for stock Whisper large-v3. Expect to correct roughly one word in three.

The model ships in the Hugging Face transformers format, so the download converts it to CTranslate2 once. The conversion needs the `convert` extra:

```bash
uv tool install --editable '.[convert]'
stt models download bengali-whisper-medium    # ~3 GB download, 1.5 GB kept
```

Then either pass `--language bn` (it picks this model because the default one has no Bengali), or pick **Record meeting in Bengali** from the menu bar. The choice is saved in the session's `session.json`, so `stt meeting transcribe` reuses it.

It runs on the CPU (CTranslate2 has no Apple GPU support): about 2x real time on an M4 Pro, so an hour of audio takes roughly 30 minutes.

---

## Speaker diarization (optional)

`--diarize` splits the remote side of a meeting into `Them 1`, `Them 2`, … using [pyannote](https://github.com/pyannote/pyannote-audio). It's a heavy extra (~2.5 GB of PyTorch) and uses gated models:

1. Accept the conditions at [pyannote/speaker-diarization-community-1](https://huggingface.co/pyannote/speaker-diarization-community-1).
2. Create a token at <https://huggingface.co/settings/tokens> and put it in the config (`[diarize] hf_token = "hf_…"`) or export `HF_TOKEN`.
3. Install the extra:
   ```bash
   uv tool install --editable '.[cuda,diarize]' --overrides overrides.txt
   ```

Without these steps everything else works unchanged. pyannote is never loaded unless you pass `--diarize`.

---

## Wayland

This project targets X11. Wayland support is implemented but **unverified**. To try it:

- **Text output:** `sudo apt install wtype wl-clipboard` (wlroots/KDE compositors) or `ydotool` (any compositor; needs the `ydotoold` daemon).
- **Hotkeys:** `sudo apt install python3-dev`, add yourself to the `input` group (`sudo usermod -aG input $USER`, then re-login), delete the `override-dependencies` line in `pyproject.toml`, and reinstall with `--extra wayland` and without `--overrides overrides.txt`.
- Backends are auto-selected per session (`[dictation] listener = "auto"`).

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| **No tray icon** | Install the GObject packages above (`python3-gi gir1.2-gtk-3.0 gir1.2-ayatanaappindicator3-0.1`), then relaunch `stt tray`. |
| **Dictation is slow** | Set `compute_type = "int8_float16"`, or use a smaller model. Confirm the GPU is used: the log says `Loaded … on cuda`. |
| **Hotkey does nothing / opens a menu** | Another app may grab `Alt+Shift+T`. Rebind it in the settings page. |
| **"Them" track is empty in meetings** | Audio was playing to a non-default output, or system volume was at zero (sink capture is post-volume). Raise volume / set the right output device. |
| **`model not downloaded`** | `stt models download large-v3-turbo`. |
| **CUDA errors on load** | It falls back to CPU automatically; for GPU, ensure a recent NVIDIA driver is installed. |
| **macOS: hotkey does nothing** | Allow Input Monitoring for the app running `stt`, then restart it. |
| **macOS: text never appears** | Allow Accessibility for the app running `stt`, then restart it. |
| **macOS: "Them" track is silent** | Allow System Audio Recording Only (see [Permissions](#permissions)). |

Logs print to the terminal that launched `stt tray` / `stt dictate`, or to `~/Library/Logs/local-stt.log` under launchd. The Mac app logs to `~/Library/Logs/io.github.hassan-mehedi.local-stt/engine.log`. Add `--debug` for full tracebacks.

History and the dictionary live in `~/.local/share/local-stt/history.db`.

---

## Development

[CONTRIBUTING.md](CONTRIBUTING.md) covers running the Mac app from source, the checks to run and where code goes. The short version:

```bash
uv sync --extra cuda --group dev    # on macOS: uv sync --group dev
uv run pytest
```

After changing dependencies, reinstall the global tool so it picks them up:

```bash
uv tool install --editable '.[cuda]' --overrides overrides.txt --reinstall
uv tool install --editable . --reinstall    # macOS
```

Models are cached in `~/.cache/local-stt/models/`; the tray writes its settings-server URL to `~/.cache/local-stt/ui.json`.
