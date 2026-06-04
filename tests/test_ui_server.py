import json
import urllib.request

import pytest

from local_stt.config import load_config
from local_stt.ui.server import Controller, SettingsServer


class FakeController(Controller):
    def __init__(self):
        self.applied = None
        self.running = True

    def daemon_running(self):
        return self.running

    def current_model(self):
        return "large-v3-turbo"

    def apply_config(self, cfg):
        self.applied = cfg


@pytest.fixture
def server(tmp_path, monkeypatch):
    # isolate config + ui state to a temp dir
    import local_stt.config as cfgmod
    import local_stt.ui.state as statemod

    monkeypatch.setattr(cfgmod, "CONFIG_PATH", tmp_path / "config.toml")
    monkeypatch.setattr(statemod, "UI_STATE_PATH", tmp_path / "ui.json")

    ctrl = FakeController()
    srv = SettingsServer(controller=ctrl)
    srv.start()
    srv.ctrl = ctrl
    yield srv
    srv.stop()


def _req(srv, path, method="GET", body=None):
    url = f"http://127.0.0.1:{srv._httpd.server_address[1]}{path}"
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        url, data=data, method=method, headers={"X-Token": srv.token}
    )
    with urllib.request.urlopen(req) as r:
        return r.status, json.loads(r.read())


def test_unauthorized_without_token(server):
    url = f"http://127.0.0.1:{server._httpd.server_address[1]}/api/state"
    with pytest.raises(urllib.error.HTTPError) as exc:
        urllib.request.urlopen(url)
    assert exc.value.code == 401


def test_state_reports_models_and_daemon(server):
    status, state = _req(server, "/api/state")
    assert status == 200
    assert state["daemon_running"] is True
    names = [m["name"] for m in state["models"]]
    assert "large-v3-turbo" in names
    assert any(m["loaded"] for m in state["models"])


def test_post_config_applies_and_persists(server):
    status, resp = _req(
        server, "/api/config", method="POST",
        body={"dictation": {"mode": "hold", "hotkey": "<ctrl>+<alt>+d"}},
    )
    assert status == 200
    assert server.ctrl.applied.dictation.mode == "hold"
    # persisted to the (temp) config file
    assert load_config().dictation.hotkey == "<ctrl>+<alt>+d"


def test_post_invalid_config_returns_400(server):
    import urllib.error

    with pytest.raises(urllib.error.HTTPError) as exc:
        _req(server, "/api/config", method="POST",
             body={"model": {"name": "bogus-model"}})
    assert exc.value.code == 400
    assert server.ctrl.applied is None  # not applied on validation failure


import urllib.error  # noqa: E402  (used in tests above)
