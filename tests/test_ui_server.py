import json
import urllib.request

import pytest

from local_stt.config import load_config
from local_stt.ui.server import Controller, SettingsServer


class FakeController(Controller):
    def __init__(self):
        self.applied = None
        self.running = True
        self.reload_error = None

    def daemon_running(self):
        return self.running

    def current_model(self):
        return "large-v3-turbo"

    def apply_config(self, cfg):
        self.applied = cfg
        if self.reload_error:
            self.running = False
        return self.reload_error

    def start_dictation(self):
        return "Model 'large-v3' is not downloaded."

    def finish_onboarding(self):
        self.finished = True


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



def test_post_config_reports_reload_failure(server):
    server.ctrl.reload_error = "Model 'medium' is not downloaded."
    status, resp = _req(
        server, "/api/config", method="POST", body={"dictation": {"mode": "hold"}}
    )
    assert status == 200
    assert resp["reload_error"] == "Model 'medium' is not downloaded."
    assert resp["daemon_running"] is False


@pytest.mark.parametrize("endpoint", ["/api/models/remove", "/api/models/download"])
def test_model_endpoints_reject_unknown_names(server, endpoint, tmp_path):
    victim = tmp_path / "victim"
    victim.mkdir()
    with pytest.raises(urllib.error.HTTPError) as exc:
        _req(server, endpoint, method="POST", body={"name": str(victim)})
    assert exc.value.code == 400
    assert victim.exists()


import urllib.error  # noqa: E402  (used in tests above)


def _get_raw(srv, path):
    url = f"http://127.0.0.1:{srv._httpd.server_address[1]}{path}"
    with urllib.request.urlopen(url) as r:
        return r.status, r.headers["Content-Type"], r.read().decode()


@pytest.mark.parametrize("path, kind, marker", [
    ("/onboarding", "text/html", "Welcome to local-stt"),
    ("/static/common.js", "text/javascript", "function hotkeyCapture"),
    ("/static/common.css", "text/css", ".model"),
])
def test_pages_and_assets_load_without_the_token(server, path, kind, marker):
    status, content_type, body = _get_raw(server, path)
    assert status == 200
    assert content_type.startswith(kind)
    assert marker in body


@pytest.mark.parametrize("path", ["/favicon.ico", "/static/../server.py"])
def test_other_paths_are_not_found(server, path):
    with pytest.raises(urllib.error.HTTPError) as exc:
        _get_raw(server, path)
    assert exc.value.code == 404


def test_onboarding_step_is_saved_until_done(server):
    _req(server, "/api/onboarding/step", method="POST", body={"step": 3})
    _, state = _req(server, "/api/state")
    assert state["onboarding"] == {"done": False, "step": 3}
    assert state["default_model"]

    _req(server, "/api/onboarding/done", method="POST", body={})
    assert server.ctrl.finished


def test_dictation_start_reports_the_controller_error(server):
    _, resp = _req(server, "/api/dictation/start", method="POST", body={})
    assert resp == {"ok": False, "error": "Model 'large-v3' is not downloaded."}


def test_permissions_state_has_every_permission(server):
    from local_stt import permissions

    _, resp = _req(server, "/api/permissions")
    assert set(resp) == {"supported", "status", "login_item", "app_bundle"}
    if resp["supported"]:
        assert set(resp["status"]) == set(permissions.NAMES)
    assert resp["app_bundle"] is False  # tests run from source


def test_unknown_permission_is_rejected(server):
    with pytest.raises(urllib.error.HTTPError) as exc:
        _req(server, "/api/permissions/request", method="POST", body={"name": "camera"})
    assert exc.value.code == 400


def test_relaunch_needs_the_app_bundle(server):
    with pytest.raises(urllib.error.HTTPError) as exc:
        _req(server, "/api/relaunch", method="POST", body={})
    assert exc.value.code == 400


def test_cleanup_key_is_saved_but_never_sent_back(server, memory_keyring):
    url = "https://api.deepseek.com"
    status, resp = _req(server, "/api/cleanup/key", "POST", {"url": url, "key": "sk-secret"})
    assert resp == {"ok": True}
    assert memory_keyring.items[("local-stt", "api.deepseek.com")] == "sk-secret"
    _req(server, "/api/config", "POST", {"cleanup": {"api_url": url}})
    _, state = _req(server, "/api/state")
    assert state["cleanup"]["key_saved"] is True
    assert "sk-secret" not in json.dumps(state)
    _req(server, "/api/cleanup/key/delete", "POST", {"url": url})
    assert _req(server, "/api/state")[1]["cleanup"]["key_saved"] is False

