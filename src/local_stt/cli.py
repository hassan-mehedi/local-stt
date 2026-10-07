"""stt — local dictation and transcription CLI."""

from __future__ import annotations

import argparse
import logging
import signal
import sys
import time
from pathlib import Path

from . import __version__
from .config import load_config


def _build_backend(cfg, model_override=None, device_override=None):
    from .engine import models

    name = model_override or cfg.model.name
    if models.spec(name).family == models.PARAKEET:
        from .engine.parakeet_mlx_backend import ParakeetMlxBackend

        return ParakeetMlxBackend(model_name=name)

    from .engine.faster_whisper_backend import FasterWhisperBackend

    return FasterWhisperBackend(
        model_name=name,
        device=device_override or cfg.model.device,
        compute_type=cfg.model.compute_type,
    )


# -- subcommands ---------------------------------------------------------------


def cmd_dictate(args) -> int:
    cfg = load_config()
    if args.model:
        cfg.model.name = args.model
    if args.hotkey:
        cfg.dictation.hotkey = args.hotkey

    from .dictation.daemon import DictationDaemon

    daemon = DictationDaemon(cfg, _build_backend(cfg))
    daemon.run()
    return 0


def cmd_file(args) -> int:
    from .engine.backend import TranscribeOptions
    from .export import FORMATS, export

    cfg = load_config()
    formats = [f.strip() for f in args.output.split(",")]
    for f in formats:
        if f not in FORMATS:
            print(
                f"Unknown format {f!r}. Available: {', '.join(FORMATS)}",
                file=sys.stderr,
            )
            return 1

    backend = _build_backend(cfg, model_override=args.model)
    out_dir = Path(args.out_dir).expanduser() if args.out_dir else None
    if out_dir:
        out_dir.mkdir(parents=True, exist_ok=True)

    for input_path in args.inputs:
        input_path = Path(input_path)

        def progress(done: float, total: float):
            pct = 100 * done / total if total else 0
            print(
                f"\r{input_path.name}: {pct:5.1f}% ({done:.0f}s / {total:.0f}s)",
                end="", file=sys.stderr, flush=True,
            )

        opts = TranscribeOptions(
            language=(args.language if args.language is not None else cfg.model.language) or None,
            batched=True,
            batch_size=args.batch_size,
            progress_cb=progress,
        )
        t0 = time.monotonic()
        transcript = backend.transcribe_file(input_path, opts)
        elapsed = time.monotonic() - t0
        print(file=sys.stderr)  # newline after \r progress
        rtf = transcript.duration / elapsed if elapsed else 0
        print(
            f"{input_path.name}: {transcript.duration:.0f}s audio in {elapsed:.1f}s "
            f"({rtf:.1f}x realtime, model={transcript.model})",
            file=sys.stderr,
        )

        base_dir = out_dir or input_path.parent
        for fmt in formats:
            dest = base_dir / f"{input_path.stem}.{fmt}"
            export(transcript, fmt, dest, title=input_path.stem)
            print(f"  wrote {dest}", file=sys.stderr)
    return 0


def _transcribe_session(
    session_dir: Path, title: str, cfg, model_override=None, language_override=None,
    diarize=False, backend=None,
) -> int:
    from .engine.backend import TranscribeOptions
    from .export import export
    from .meeting.transcribe import choose_model, load_settings, transcribe_meeting

    mic_wav = session_dir / "raw" / "mic.wav"
    system_wav = session_dir / "raw" / "system.wav"
    for p in (mic_wav, system_wav):
        if not p.exists():
            print(f"error: {p} not found — not a meeting session dir?", file=sys.stderr)
            return 1

    # what the session was recorded with, unless overridden now
    saved = load_settings(session_dir)
    model, language = choose_model(
        cfg,
        model_override or saved.get("model"),
        language_override if language_override is not None else saved.get("language"),
    )

    # Reuse a caller-supplied backend (e.g. the tray's resident dictation
    # model) instead of loading a second copy into VRAM.
    owns_backend = backend is None
    if backend is None:
        backend = _build_backend(cfg, model_override=model)
    print(f"  model {model}, language {language or 'auto'}", file=sys.stderr)

    def progress(done: float, total: float):
        pct = 100 * done / total if total else 0
        print(f"\r  {pct:5.1f}%", end="", file=sys.stderr, flush=True)

    opts = TranscribeOptions(
        language=language or None,
        batched=True,
        progress_cb=progress,
    )
    transcript = transcribe_meeting(mic_wav, system_wav, backend, opts)
    print(file=sys.stderr)

    if diarize:
        from dataclasses import replace

        from .meeting.diarize import assign_speakers, diarize_wav

        if owns_backend:
            backend.unload()  # free VRAM before loading pyannote
        print("  diarizing the Them track...", file=sys.stderr)
        turns = diarize_wav(system_wav, hf_token=cfg.diarize.hf_token or None)
        them = [s for s in transcript.segments if s.speaker == "Them"]
        relabeled = {id(s): r for s, r in zip(them, assign_speakers(them, turns))}
        transcript = replace(
            transcript,
            segments=[relabeled.get(id(s), s) for s in transcript.segments],
        )
        n = len({s.speaker for s in transcript.segments if s.speaker != "Me"})
        print(f"  found {n} remote speaker(s)", file=sys.stderr)

    for fmt in ("md", "json", "srt"):
        dest = session_dir / f"transcript.{fmt}"
        export(transcript, fmt, dest, title=title)
        print(f"  wrote {dest}", file=sys.stderr)
    return 0


def cmd_meeting(args) -> int:
    from datetime import datetime

    from .meeting.recorder import MeetingRecorder, signal_running_session

    cfg = load_config()

    if args.action == "stop":
        if signal_running_session():
            print("Stop signal sent to the running meeting session.", file=sys.stderr)
            return 0
        print("No meeting session is running.", file=sys.stderr)
        return 1

    if args.action == "transcribe":
        if not args.dir:
            print("error: stt meeting transcribe <session-dir>", file=sys.stderr)
            return 1
        session_dir = Path(args.dir).expanduser().resolve()
        return _transcribe_session(
            session_dir, title=session_dir.name, cfg=cfg,
            model_override=args.model, language_override=args.language,
            diarize=args.diarize,
        )

    from .meeting.transcribe import choose_model, save_settings

    model, language = choose_model(cfg, args.model, args.language)  # fail before recording
    title = args.name or "meeting"
    out_root = Path(cfg.meeting.output_dir).expanduser()
    recorder = MeetingRecorder(out_root, title, when=datetime.now())

    recorder.start()
    save_settings(recorder.session_dir, model, language)
    print(
        f"Recording to {recorder.session_dir}\n"
        "  mic -> Me, system audio -> Them\n"
        "  Stop with Ctrl+C (or: stt meeting stop)",
        file=sys.stderr,
    )
    try:
        signal.pause()  # record until SIGINT
    except KeyboardInterrupt:
        pass
    recorder.stop()
    print("\nRecording stopped. Transcribing...", file=sys.stderr)
    return _transcribe_session(
        recorder.session_dir,
        title=f"{title} — {datetime.now():%Y-%m-%d}",
        cfg=cfg,
        diarize=args.diarize,
    )


def cmd_tray(args) -> int:
    from . import tray

    return tray.main()


def cmd_engine(args) -> int:
    from . import helper

    return helper.main()


def cmd_settings(args) -> int:
    import time

    from .desktop import open_target
    from .ui.state import read_state

    # if the tray's server is already up, just open it
    existing = read_state()
    if existing and _server_alive(existing):
        print(f"Opening {existing['url']}", file=sys.stderr)
        open_target(existing["url"])
        return 0

    # otherwise run a standalone (config-only) server until Ctrl+C
    from .ui.server import SettingsServer

    server = SettingsServer()
    url = server.start()
    print(
        f"Settings at {url}\n(standalone — daemon not running; edits save to "
        "config.toml)\nPress Ctrl+C to stop.",
        file=sys.stderr,
    )
    open_target(url)
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        pass
    finally:
        server.stop()
    return 0


def _server_alive(state: dict) -> bool:
    import urllib.error
    import urllib.request

    try:
        req = urllib.request.Request(
            f"http://127.0.0.1:{state['port']}/api/state",
            headers={"X-Token": state["token"]},
        )
        urllib.request.urlopen(req, timeout=1).read()
        return True
    except (urllib.error.URLError, OSError, KeyError):
        return False


def cmd_models(args) -> int:
    from .engine import models

    if args.models_cmd == "list":
        for spec in models.MODELS.values():
            mark = "✓ downloaded" if models.is_downloaded(spec.name) else "  -"
            reason = models.unavailable_reason(spec.name)
            note = f"  ({reason})" if reason else ""
            print(
                f"{spec.name:22s} {spec.family:8s} {spec.languages_label:22s} "
                f"{mark}{note}"
            )
        return 0
    if args.models_cmd == "download":
        print(f"Downloading {args.name}...", file=sys.stderr)
        models.download(args.name)
        print(f"Done: {models.model_dir(args.name)}", file=sys.stderr)
        return 0
    if args.models_cmd == "remove":
        models.remove(args.name)
        print(f"Removed {args.name}", file=sys.stderr)
        return 0
    return 1


# -- entry point -----------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="stt", description=__doc__)
    p.add_argument("--version", action="version", version=f"local-stt {__version__}")
    p.add_argument("--debug", action="store_true", help="show tracebacks and debug logs")
    sub = p.add_subparsers(dest="cmd", required=True)

    d = sub.add_parser("dictate", help="push-to-talk dictation daemon")
    d.add_argument("--model", help="override configured model")
    d.add_argument("--hotkey", help="override configured hotkey, e.g. '<alt>+t'")
    d.set_defaults(func=cmd_dictate)

    f = sub.add_parser("file", help="transcribe audio/video files")
    f.add_argument("inputs", nargs="+", help="input media files")
    f.add_argument(
        "-o", "--output", default="txt",
        help="comma-separated formats: txt,md,srt,vtt,json (default: txt)",
    )
    f.add_argument("--out-dir", help="write outputs here instead of next to inputs")
    f.add_argument("--model", help="override configured model")
    f.add_argument("--language", help="language code, empty for auto-detect")
    f.add_argument("--batch-size", type=int, default=8)
    f.set_defaults(func=cmd_file)

    mt = sub.add_parser("meeting", help="record + transcribe a meeting (Me/Them tracks)")
    mt.add_argument(
        "action", nargs="?", default="record",
        choices=["record", "stop", "transcribe"],
        help="'record' (default), 'stop' a session running in another "
        "terminal, or '(re)transcribe' an existing session directory",
    )
    mt.add_argument(
        "dir", nargs="?",
        help="session directory (only for 'transcribe')",
    )
    mt.add_argument("--name", help="meeting title (used in the output directory name)")
    mt.add_argument("--model", help="override configured model")
    mt.add_argument(
        "--language",
        help="meeting language, e.g. 'bn'; picks a downloaded model for it if the "
        "configured one can't do it",
    )
    mt.add_argument(
        "--diarize", action="store_true",
        help="split remote speakers with pyannote (needs [diarize] extra + HF token)",
    )
    mt.set_defaults(func=cmd_meeting)

    t = sub.add_parser("tray", help="system tray app (dictation on by default)")
    t.set_defaults(func=cmd_tray)

    e = sub.add_parser(
        "engine",
        help="the engine behind the desktop app: prints its port and token, "
        "then serves its API until stdin closes",
    )
    e.set_defaults(func=cmd_engine)

    st = sub.add_parser("settings", help="open the settings page in a browser")
    st.set_defaults(func=cmd_settings)

    m = sub.add_parser("models", help="manage local models")
    msub = m.add_subparsers(dest="models_cmd", required=True)
    msub.add_parser("list", help="list known models and download status")
    dl = msub.add_parser("download", help="download a model")
    dl.add_argument("name")
    rm = msub.add_parser("remove", help="delete a downloaded model")
    rm.add_argument("name")
    m.set_defaults(func=cmd_models)

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )
    if not args.debug:
        for noisy in ("faster_whisper", "httpx"):  # httpx logs every HF request
            logging.getLogger(noisy).setLevel(logging.WARNING)
    try:
        return args.func(args)
    except KeyboardInterrupt:
        return 130
    except Exception as e:
        if args.debug:
            raise
        print(f"error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
