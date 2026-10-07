"""The API the desktop app adds on top of the settings API: history, stats,
dictionary, meetings and dictation control. Each route returns a JSON-able
object, or a FileReply for audio."""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from .. import permissions
from ..export import FORMATS, export
from ..meeting import library


@dataclass(frozen=True)
class FileReply:
    path: Path
    content_type: str


def _int(value, name: str) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        raise ValueError(f"{name} must be a number") from None


def _first(query: dict, key: str, default: str = "") -> str:
    return query.get(key, [default])[0]


def handle_get(controller, path: str, query: dict):
    """Returns the reply, or None when the path is not an app route."""
    store = controller.store
    if path == "/api/history":
        before = _first(query, "before")
        return store.history(
            query=_first(query, "q").strip(),
            before=_int(before, "before") if before else None,
            limit=min(_int(_first(query, "limit", "50"), "limit"), 200),
        )
    if m := re.fullmatch(r"/api/history/(\d+)/audio", path):
        audio = store.audio_path(int(m.group(1)))
        if not audio.exists():
            raise LookupError("no recording for this dictation")
        return FileReply(audio, "audio/wav")
    if path == "/api/stats":
        return store.home_stats()
    if path == "/api/insights":
        return store.insights(_first(query, "range", "month"))
    if path == "/api/dictionary":
        return store.dictionary()
    if path == "/api/meetings":
        return {
            "items": library.list_sessions(
                controller.meetings_dir(), controller.meeting_activity()
            ),
            "recording": controller.meeting_activity().get("recording"),
            "folder": str(controller.meetings_dir()),
        }
    if m := re.fullmatch(r"/api/meetings/([^/]+)", path):
        return library.session_detail(
            controller.meetings_dir(), m.group(1), controller.meeting_activity()
        )
    if m := re.fullmatch(r"/api/meetings/([^/]+)/audio", path):
        return FileReply(library.mixed_audio(controller.meetings_dir(), m.group(1)), "audio/wav")
    if m := re.fullmatch(r"/api/meetings/([^/]+)/waveform", path):
        mix = library.mixed_audio(controller.meetings_dir(), m.group(1))
        return {"peaks": library.waveform(mix)}
    return None


def handle_post(controller, path: str, body: dict):
    """Returns the reply, or None when the path is not an app route."""
    store = controller.store
    if path == "/api/dictation/toggle":
        error = controller.toggle_recording()
        return {"ok": error is None, "error": error}
    if path == "/api/dictation/cancel":
        return {"ok": controller.cancel_recording()}
    if path == "/api/dictation/stop":
        controller.stop_dictation()
        return {"ok": True}
    if path == "/api/meeting/toggle":
        error = controller.toggle_meeting(body.get("language") or None)
        return {"ok": error is None, "error": error}
    if path == "/api/meetings/transcribe":
        library.session_dir(controller.meetings_dir(), body.get("id", ""))
        controller.retranscribe_meeting(body["id"])
        return {"ok": True}
    if path == "/api/meetings/reveal":
        folder = library.session_dir(controller.meetings_dir(), body.get("id", ""))
        _reveal(folder)
        return {"ok": True}
    if path == "/api/meetings/open-folder":
        folder = controller.meetings_dir()
        folder.mkdir(parents=True, exist_ok=True)
        _reveal(folder, select=False)
        return {"ok": True}
    if path == "/api/meetings/export":
        return _export_meeting(controller, body)
    if path == "/api/history/delete":
        return {"ok": store.delete_dictation(_int(body.get("id"), "id"))}
    if path == "/api/history/paste":
        row = store.dictation(_int(body.get("id"), "id"))
        if row is None:
            raise LookupError("that dictation is gone")
        error = controller.paste_text(row["text"])
        return {"ok": error is None, "error": error}
    if path == "/api/dictionary/add":
        return store.add_entry(
            body.get("kind", ""), body.get("phrase", ""), body.get("value", "")
        )
    if path == "/api/dictionary/delete":
        return {"ok": store.delete_entry(_int(body.get("id"), "id"))}
    if path == "/api/permissions/open":
        name = body.get("name", "")
        if name not in permissions.NAMES:
            raise ValueError(f"unknown permission {name!r}")
        permissions.open_settings(name)
        return {"ok": True}
    return None


def _reveal(path: Path, select: bool = True) -> None:
    if sys.platform == "darwin":
        subprocess.Popen(["open", "-R", str(path)] if select else ["open", str(path)])
    else:
        subprocess.Popen(["xdg-open", str(path if not select else path.parent)])


def _export_meeting(controller, body: dict) -> dict:
    fmt = body.get("format", "")
    if fmt not in FORMATS:
        raise ValueError(f"unknown format {fmt!r}")
    dest = Path(body.get("dest", "")).expanduser()
    if not dest.is_absolute():
        raise ValueError("pick where to save the file")
    folder = library.session_dir(controller.meetings_dir(), body.get("id", ""))
    existing = folder / f"transcript.{fmt}"
    if existing.exists():
        shutil.copyfile(existing, dest)
    else:
        transcript = library.load_transcript(folder)
        if transcript is None:
            raise ValueError("this meeting has no transcript yet")
        title = library.session_detail(controller.meetings_dir(), folder.name)["title"]
        export(transcript, fmt, dest, title=title)
    return {"ok": True, "path": str(dest)}
