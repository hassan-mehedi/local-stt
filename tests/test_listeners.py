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


def test_mac_matches_trigger_by_key_code():
    from pynput.keyboard import KeyCode, Listener

    lst = PynputListener(parse_hotkey("<alt>+<shift>+t"), lambda: None, lambda: None)
    lst._listener = Listener()  # real canonical(), never started
    lst._trigger_vks = frozenset({17})
    assert lst._is_trigger(KeyCode.from_char("ˇ", vk=17))  # Option+Shift+T
    assert not lst._is_trigger(KeyCode.from_char("t", vk=11))


@pytest.mark.skipif(__import__("sys").platform != "darwin", reason="macOS keyboard layout")
def test_mac_keycodes_for_us_layout():
    from local_stt.dictation.listeners import mac_keycodes

    assert 17 in mac_keycodes("t")
    assert {18, 83} <= mac_keycodes("1")  # main row and keypad


def test_lone_modifier_trigger_fires_on_its_own():
    from pynput.keyboard import Key, Listener

    events = []
    lst = PynputListener(parse_hotkey("alt_r"), lambda: events.append("on"), lambda: events.append("off"))
    lst._listener = Listener()
    lst._on_press(Key.alt_r)
    lst._on_release(Key.alt_r)
    assert events == ["on", "off"]


def test_lone_modifier_trigger_ignores_the_other_side():
    from pynput.keyboard import Key, KeyCode, Listener

    events = []
    lst = PynputListener(parse_hotkey("alt_r"), lambda: events.append("on"), lambda: events.append("off"))
    lst._listener = Listener()
    for key in (Key.alt, Key.alt_l, KeyCode.from_char("t")):
        lst._on_press(key)
        lst._on_release(key)
    assert events == []


def test_lone_modifier_with_a_held_modifier():
    from pynput.keyboard import Key, Listener

    events = []
    lst = PynputListener(parse_hotkey("<ctrl>+alt_r"), lambda: events.append("on"), lambda: None)
    lst._listener = Listener()
    lst._on_press(Key.alt_r)
    lst._on_release(Key.alt_r)
    assert events == []
    lst._on_press(Key.ctrl)
    lst._on_press(Key.alt_r)
    assert events == ["on"]


@pytest.mark.skipif(__import__("sys").platform != "darwin", reason="macOS keyboard layout")
def test_mac_layout_snapshot_is_read_on_the_main_thread(monkeypatch):
    import threading

    from local_stt.dictation import mac_layout

    monkeypatch.setattr(mac_layout, "_layout", None)
    errors = []

    def off_main():
        try:
            mac_layout.use_snapshot()
        except RuntimeError as e:
            errors.append(e)

    t = threading.Thread(target=off_main)
    t.start()
    t.join()
    assert errors
