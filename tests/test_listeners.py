import pytest

from local_stt.dictation.hotkey import parse_hotkey
from local_stt.dictation.listeners import PynputListener, is_wayland, make_listener


def test_is_wayland_env(monkeypatch):
    monkeypatch.setenv("XDG_SESSION_TYPE", "x11")
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    assert not is_wayland()
    monkeypatch.setenv("XDG_SESSION_TYPE", "wayland")
    assert is_wayland()
    monkeypatch.setenv("XDG_SESSION_TYPE", "x11")
    monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")
    assert is_wayland()


def test_make_listener_auto_x11(monkeypatch):
    monkeypatch.setenv("XDG_SESSION_TYPE", "x11")
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    lst = make_listener("auto", parse_hotkey("<alt>+t"), lambda: None, lambda: None)
    assert isinstance(lst, PynputListener)


def test_make_listener_unknown():
    with pytest.raises(ValueError):
        make_listener("nope", parse_hotkey("<alt>+t"), lambda: None, lambda: None)


def test_evdev_listener_helpful_error_without_evdev(monkeypatch):
    # evdev is intentionally excluded from this environment
    with pytest.raises((RuntimeError, ValueError)) as exc:
        make_listener("evdev", parse_hotkey("<alt>+t"), lambda: None, lambda: None)
    assert "evdev" in str(exc.value)
