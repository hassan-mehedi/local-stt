import json
import urllib.error
import urllib.request
import wave
from pathlib import Path

import numpy as np
import pytest

from local_stt.store import Store
from local_stt.ui.events import EventBus
from local_stt.ui.server import Controller, SettingsServer


class AppController(Controller):
    def __init__(self, store, meetings):
        self.store = store
        self.events = EventBus()
        self._meetings = meetings
        self.pasted = []
        self.toggled = 0

    def meetings_dir(self):
        return self._meetings

    def meeting_activity(self):
        return {"recording": None, "transcribing": set()}

    def toggle_recording(self):
        self.toggled += 1
        return None

    def paste_text(self, text):
        self.pasted.append(text)
        return None

    def publish_state(self):
        self.events.publish("state", {"dictation": "idle"})


def _write_wav(path: Path, seconds: float, value: float = 0.1) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes((np.full(int(16000 * seconds), value) * 32767).astype("<i2").tobytes())


@pytest.fixture
def app(tmp_path, monkeypatch):
    import local_stt.config as cfgmod
    import local_stt.meeting.library as libmod
    import local_stt.ui.state as statemod

    monkeypatch.setattr(cfgmod, "CONFIG_PATH", tmp_path / "config.toml")
    monkeypatch.setattr(statemod, "UI_STATE_PATH", tmp_path / "ui.json")
    monkeypatch.setattr(libmod, "MIX_DIR", tmp_path / "mix")
    store = Store(tmp_path / "history.db")
    ctrl = AppController(store, tmp_path / "meetings")
    srv = SettingsServer(controller=ctrl)
    srv.start()
    srv.ctrl = ctrl
    srv.base = f"http://127.0.0.1:{srv._httpd.server_address[1]}"
    yield srv
    srv.stop()
    store.close()


def _req(srv, path, method="GET", body=None, headers=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        srv.base + path, data=data, method=method,
        headers={"X-Token": srv.token, **(headers or {})},
    )
    with urllib.request.urlopen(req) as r:
        return r.status, dict(r.headers), r.read()


def _json(srv, path, method="GET", body=None):
    return json.loads(_req(srv, path, method, body)[2])


def test_cors_only_for_the_app_origin(app):
    _, headers, _ = _req(app, "/api/stats", headers={"Origin": "tauri://localhost"})
    assert headers["Access-Control-Allow-Origin"] == "tauri://localhost"
    _, headers, _ = _req(app, "/api/stats", headers={"Origin": "https://example.com"})
    assert "Access-Control-Allow-Origin" not in headers


def test_preflight_needs_no_token(app):
    req = urllib.request.Request(
        app.base + "/api/dictionary/add", method="OPTIONS",
        headers={"Origin": "http://localhost:1420"},
    )
    with urllib.request.urlopen(req) as r:
        assert r.status == 204
        assert "X-Token" in r.headers["Access-Control-Allow-Headers"]


def test_app_routes_need_the_token(app):
    with pytest.raises(urllib.error.HTTPError) as exc:
        urllib.request.urlopen(app.base + "/api/history")
    assert exc.value.code == 401


def test_history_paste_and_delete(app):
    row = app.ctrl.store.add_dictation("hello there", 1000, 10, pcm=np.zeros(1600, np.float32))
    items = _json(app, "/api/history")["items"]
    assert [i["text"] for i in items] == ["hello there"]
    assert _json(app, "/api/history/paste", "POST", {"id": row["id"]})["ok"]
    assert app.ctrl.pasted == ["hello there"]
    assert _json(app, "/api/history/delete", "POST", {"id": row["id"]})["ok"]
    assert _json(app, "/api/history")["items"] == []
    with pytest.raises(urllib.error.HTTPError) as exc:
        _json(app, "/api/history/paste", "POST", {"id": row["id"]})
    assert exc.value.code == 404


def test_audio_supports_byte_ranges(app):
    row = app.ctrl.store.add_dictation("clip", 100, 10, pcm=np.zeros(1600, np.float32))
    path = f"/api/history/{row['id']}/audio"
    status, headers, body = _req(app, path)
    assert status == 200 and headers["Accept-Ranges"] == "bytes"
    full = len(body)
    status, headers, body = _req(app, path, headers={"Range": "bytes=0-1"})
    assert status == 206
    assert body == b"RI"
    assert headers["Content-Range"] == f"bytes 0-1/{full}"


def test_dictionary_add_rejects_bad_input(app):
    assert _json(app, "/api/dictionary/add", "POST", {"kind": "words", "phrase": "MLX"})["phrase"] == "MLX"
    with pytest.raises(urllib.error.HTTPError) as exc:
        _json(app, "/api/dictionary/add", "POST", {"kind": "words", "phrase": "mlx"})
    assert exc.value.code == 400


def test_dictation_toggle_reaches_controller(app):
    assert _json(app, "/api/dictation/toggle", "POST", {})["ok"]
    assert app.ctrl.toggled == 1


def test_events_stream_starts_with_state(app):
    with urllib.request.urlopen(f"{app.base}/api/events?token={app.token}", timeout=5) as r:
        assert r.headers["Content-Type"] == "text/event-stream"
        lines = [r.readline() for _ in range(4)]
    assert b"event: state\n" in lines


def test_meetings_list_detail_and_audio(app):
    folder = app.ctrl.meetings_dir() / "2026-10-07-14-05"
    _write_wav(folder / "raw" / "mic.wav", 2.0)
    _write_wav(folder / "raw" / "system.wav", 1.0)
    (folder / "transcript.json").write_text(json.dumps({
        "segments": [{"start": 0.0, "end": 1.0, "text": " Hi ", "words": [], "speaker": "Me"}],
        "language": "en", "duration": 2.0, "model": "parakeet-tdt-0.6b-v2",
    }))
    items = _json(app, "/api/meetings")["items"]
    assert items == [{
        "id": "2026-10-07-14-05", "title": "Meeting at 14:05", "started_at": "2026-10-07T14:05",
        "duration_s": 2, "language": "", "model": "", "status": "ready",
    }]
    detail = _json(app, "/api/meetings/2026-10-07-14-05")
    assert detail["segments"] == [{"start": 0.0, "end": 1.0, "speaker": "Me", "text": "Hi"}]
    peaks = _json(app, "/api/meetings/2026-10-07-14-05/waveform")["peaks"]
    assert len(peaks) == 120 and max(peaks) == 1.0
    status, headers, _ = _req(app, "/api/meetings/2026-10-07-14-05/audio")
    assert status == 200 and headers["Content-Type"] == "audio/wav"


def test_meeting_ids_cannot_leave_the_folder(app):
    for bad in ("..", ".hidden", "missing"):
        with pytest.raises(urllib.error.HTTPError) as exc:
            _json(app, f"/api/meetings/{bad}")
        assert exc.value.code in (400, 404)


def test_meeting_export_writes_the_format(app, tmp_path):
    folder = app.ctrl.meetings_dir() / "2026-10-07-standup"
    _write_wav(folder / "raw" / "mic.wav", 1.0)
    (folder / "transcript.json").write_text(json.dumps({
        "segments": [{"start": 0.0, "end": 1.0, "text": "Done", "words": [], "speaker": "Them"}],
        "language": "en", "duration": 1.0, "model": "m",
    }))
    dest = tmp_path / "out.srt"
    _json(app, "/api/meetings/export", "POST", {"id": folder.name, "format": "srt", "dest": str(dest)})
    assert "Them: Done" in dest.read_text()
    assert _json(app, "/api/meetings")["items"][0]["title"] == "Standup"
