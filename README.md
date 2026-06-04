# local-stt

Local, offline speech-to-text for Linux. Press a hotkey, speak, press again — the text appears in whatever app has focus. Also transcribes audio/video files and records meetings (your mic + the other side) with speaker labels. Everything runs on your machine: no cloud, no account, no telemetry.

- **Dictation** — global hotkey toggles recording; transcribes and types into the focused window.
- **File transcription** — any audio/video → `txt` / `md` / `srt` / `vtt` / `json`.
- **Meetings** — records mic ("Me") and system audio ("Them") as separate tracks, transcribes and merges them. Optional speaker diarization.
- **Tray app** — status icon + menu, with a browser-based settings page (switch models, rebind the hotkey, manage downloads).

Powered by [faster-whisper](https://github.com/SYSTRAN/faster-whisper) (CTranslate2). Uses your NVIDIA GPU if present, falls back to CPU.

See [SPEC.md](SPEC.md) for the full design.

---

## Requirements

- **Linux on X11.** Tested on Linux Mint / Cinnamon. (Wayland support exists but is unverified — see [below](#wayland).)
- **Python 3.11+**
- **NVIDIA GPU (optional but recommended).** Needs a recent proprietary driver. Without one it runs on CPU — fine for file transcription, slow for dictation. No CUDA toolkit needed; the CUDA libraries install via pip.
- **[uv](https://docs.astral.sh/uv/)** — the Python project/installer used here:
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

> The tray uses your **system** PyGObject, not a pip package — these GObject-introspection packages are required for the tray icon to appear. On Mint they're usually preinstalled.

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

`stt` is now on your PATH. (The `--overrides overrides.txt` flag skips an optional Linux build dependency that's only needed for Wayland — see [below](#wayland).)

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

Only one tray runs at a time — the service plus a manual `stt tray` won't double up (a second instance just exits).

> Prefer a desktop autostart entry instead? Create `~/.config/autostart/local-stt-tray.desktop` with `Exec=` pointing at `$(command -v stt) tray`. The systemd service is recommended (auto-restart + journald logs); don't enable both.

---

## Usage

```bash
# Dictation — press Alt+Shift+T to start, press again to stop (default: toggle mode)
stt dictate

# Transcribe files
stt file recording.mp3 -o md,srt,json
stt file lecture.mp4 --language en --out-dir ~/transcripts

# Tray app (status icon + settings)
stt tray

# Settings page in your browser (model, hotkey, modes, downloads)
stt settings                              # or the tray's "Settings…" item

# Meetings — records mic (Me) + system audio (Them), transcribes on stop
stt meeting --name "weekly standup"
stt meeting stop                          # from another terminal, or just Ctrl+C
stt meeting transcribe <session-dir>      # (re)transcribe an existing recording
stt meeting --name "standup" --diarize    # split remote speakers (see below)

# Models
stt models list
stt models download medium
stt models remove medium
```

> **Tip:** for meetings, use headphones. On speakers, the other side's voice leaks into your mic and shows up under both "Me" and "Them".

---

## Settings UI

`stt settings` (or the tray's **Settings…** item) opens a local page served on `127.0.0.1` with a per-session token — no internet involved. From it you can:

- switch the active model, and download/remove models;
- rebind the dictation hotkey by **pressing** the combo;
- change mode (toggle/hold), output (type/clipboard), language, and the meetings folder;
- set a Hugging Face token for diarization.

**Apply** restarts the dictation daemon in place — changes take effect immediately, no logout. Edits are written to `config.toml` with your comments preserved.

---

## Configuration

`~/.config/local-stt/config.toml` — created on first save; every key is optional and falls back to the defaults below.

```toml
[model]
name = "large-v3-turbo"       # see the model table below
compute_type = "float16"      # try "int8_float16" if latency is poor or VRAM is tight
device = "auto"               # "auto" | "cuda" | "cpu"
language = "en"               # "" = auto-detect

[dictation]
hotkey = "<alt>+<shift>+t"
mode = "toggle"               # "toggle" (press start/stop) | "hold" (push-to-talk)
output = "type"               # "type" (xdotool) | "clipboard" (xclip + Ctrl+V)
listener = "auto"             # "auto" | "pynput" (X11) | "evdev" (Wayland)
min_duration_ms = 300         # ignore shorter recordings
max_duration_ms = 300000      # toggle-mode auto-stop after this long (0 = off)
append_space = true
notify = true

[meeting]
output_dir = "~/Documents/meetings"

[diarize]
hf_token = ""                 # Hugging Face token (or set HF_TOKEN); see below
```

---

## Models

All run offline once downloaded (cached in `~/.cache/local-stt/models/`). Pick with `stt models download <name>` and select in the settings page or `[model] name`.

| Model | Size | Notes |
|---|---|---|
| `large-v3-turbo` | ~1.6 GB | **Default.** Best quality/speed balance; great on a 6 GB+ GPU. |
| `large-v3` | ~3 GB | Highest quality, slower. |
| `distil-large-v3` | ~1.5 GB | Faster, English-leaning. |
| `medium` | ~1.5 GB | Good on smaller GPUs. |
| `small` / `base` / `tiny` | 484 / 145 / 75 MB | Lightweight; CPU-friendly, lower accuracy. |

If a model won't fit in VRAM, set `compute_type = "int8_float16"` (or `"int8"`), or choose a smaller model.

---

## Speaker diarization (optional)

`--diarize` splits the remote side of a meeting into `Them 1`, `Them 2`, … using [pyannote](https://github.com/pyannote/pyannote-audio). It's a heavy extra (~2.5 GB of PyTorch) and uses gated models:

1. Accept the conditions at [pyannote/speaker-diarization-3.1](https://huggingface.co/pyannote/speaker-diarization-3.1) and [pyannote/segmentation-3.0](https://huggingface.co/pyannote/segmentation-3.0).
2. Create a token at <https://huggingface.co/settings/tokens> and put it in the config (`[diarize] hf_token = "hf_…"`) or export `HF_TOKEN`.
3. Install the extra:
   ```bash
   uv tool install --editable '.[cuda,diarize]' --overrides overrides.txt
   ```

Without these steps everything else works unchanged — pyannote is never loaded unless you pass `--diarize`.

---

## Wayland

This project targets X11. Wayland support is implemented but **unverified**. To try it:

- **Text output:** `sudo apt install wtype wl-clipboard` (wlroots/KDE compositors) or `ydotool` (any compositor; needs the `ydotoold` daemon).
- **Hotkeys:** `sudo apt install python3-dev`, add yourself to the `input` group (`sudo usermod -aG input $USER`, then re-login), delete the `override-dependencies` line in `pyproject.toml`, and reinstall with `--extra wayland`.
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

Logs print to the terminal that launched `stt tray` / `stt dictate`. Add `--debug` for full tracebacks.

---

## Development

```bash
uv sync --extra cuda --group dev
uv run pytest
```

After changing dependencies, reinstall the global tool so it picks them up:

```bash
uv tool install --editable '.[cuda]' --overrides overrides.txt --reinstall
```

Models are cached in `~/.cache/local-stt/models/`; the tray writes its settings-server URL to `~/.cache/local-stt/ui.json`.
