"""Hotkey listener backends.

PynputListener — X11 (no special permissions).
EvdevListener  — Wayland (reads /dev/input directly; user must be in the
                 'input' group and the [wayland] extra installed).

Both call on_activate() when the full combo goes down and on_deactivate()
when the trigger key is released. Callbacks must not block.
"""

from __future__ import annotations

import logging
import os
import threading

from .hotkey import Hotkey

log = logging.getLogger(__name__)


class PynputListener:
    def __init__(self, hotkey: Hotkey, on_activate, on_deactivate):
        self.hotkey = hotkey
        self.on_activate = on_activate
        self.on_deactivate = on_deactivate
        self._pressed_mods: set[str] = set()
        self._trigger_down = False  # edge detection: X auto-repeat resends presses
        self._listener = None

    @staticmethod
    def _mod_name(key) -> str | None:
        from pynput.keyboard import Key

        mapping = {
            Key.cmd: "super", Key.cmd_l: "super", Key.cmd_r: "super",
            Key.ctrl: "ctrl", Key.ctrl_l: "ctrl", Key.ctrl_r: "ctrl",
            Key.alt: "alt", Key.alt_l: "alt", Key.alt_r: "alt", Key.alt_gr: "alt",
            Key.shift: "shift", Key.shift_l: "shift", Key.shift_r: "shift",
        }
        return mapping.get(key)

    def _is_trigger(self, key) -> bool:
        from pynput.keyboard import Key, KeyCode

        key = self._listener.canonical(key)
        trigger = self.hotkey.trigger
        if isinstance(key, KeyCode):
            if key.char is not None and key.char.lower() == trigger:
                return True
            # with modifiers held, X11 may deliver a vk instead of a char
            if len(trigger) == 1 and key.vk is not None:
                return key.vk == ord(trigger.upper())
            return False
        if isinstance(key, Key):
            return key.name == trigger
        return False

    def _on_press(self, key):
        mod = self._mod_name(key)
        if mod:
            self._pressed_mods.add(mod)
            return
        if self._is_trigger(key):
            if self._trigger_down:
                return  # auto-repeat
            self._trigger_down = True
            if self.hotkey.modifiers <= self._pressed_mods:
                self.on_activate()

    def _on_release(self, key):
        mod = self._mod_name(key)
        if mod:
            self._pressed_mods.discard(mod)
            return
        if self._is_trigger(key):
            self._trigger_down = False
            self.on_deactivate()

    def start(self) -> None:
        from pynput import keyboard

        self._listener = keyboard.Listener(
            on_press=self._on_press, on_release=self._on_release
        )
        self._listener.start()

    def stop(self) -> None:
        if self._listener is not None:
            self._listener.stop()
            self._listener = None

    def join(self) -> None:
        if self._listener is not None:
            self._listener.join()


class EvdevListener:
    """Kernel-level key listener for Wayland sessions."""

    _MODS = {
        "KEY_LEFTMETA": "super", "KEY_RIGHTMETA": "super",
        "KEY_LEFTCTRL": "ctrl", "KEY_RIGHTCTRL": "ctrl",
        "KEY_LEFTALT": "alt", "KEY_RIGHTALT": "alt",
        "KEY_LEFTSHIFT": "shift", "KEY_RIGHTSHIFT": "shift",
    }

    def __init__(self, hotkey: Hotkey, on_activate, on_deactivate):
        try:
            import evdev  # noqa: F401
        except ImportError:
            raise RuntimeError(
                "evdev is required for Wayland hotkeys. Install it with:\n"
                "  sudo apt install python3-dev\n"
                "  (then remove the evdev override from pyproject.toml and run)\n"
                "  uv sync --extra cuda --extra wayland"
            ) from None
        self.hotkey = hotkey
        self.on_activate = on_activate
        self.on_deactivate = on_deactivate
        self._trigger_code = self._resolve_trigger(hotkey.trigger)
        self._pressed_mods: set[str] = set()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    @staticmethod
    def _resolve_trigger(trigger: str) -> int:
        from evdev import ecodes

        name = f"KEY_{trigger.upper()}"
        code = getattr(ecodes, name, None)
        if code is None:
            raise ValueError(f"Unknown trigger key for evdev: {trigger!r} ({name})")
        return code

    def _keyboards(self):
        import evdev
        from evdev import ecodes

        devs = []
        for path in evdev.list_devices():
            try:
                d = evdev.InputDevice(path)
                caps = d.capabilities().get(ecodes.EV_KEY, [])
                if ecodes.KEY_A in caps and ecodes.KEY_Z in caps:
                    devs.append(d)
                else:
                    d.close()
            except (OSError, PermissionError):
                continue
        if not devs:
            raise RuntimeError(
                "No readable keyboards in /dev/input. Add yourself to the "
                "'input' group:\n  sudo usermod -aG input $USER  (then re-login)"
            )
        return devs

    def _loop(self) -> None:
        import select

        from evdev import ecodes

        devices = self._keyboards()
        fd_map = {d.fd: d for d in devices}
        try:
            while not self._stop.is_set():
                r, _, _ = select.select(fd_map, [], [], 0.5)
                for fd in r:
                    for ev in fd_map[fd].read():
                        if ev.type != ecodes.EV_KEY or ev.value == 2:  # ignore repeat
                            continue
                        self._handle(ev.code, pressed=ev.value == 1)
        finally:
            for d in devices:
                d.close()

    def _handle(self, code: int, pressed: bool) -> None:
        from evdev import ecodes

        name = ecodes.KEY.get(code)
        name = name[0] if isinstance(name, list) else name
        mod = self._MODS.get(name or "")
        if mod:
            (self._pressed_mods.add if pressed else self._pressed_mods.discard)(mod)
            return
        if code == self._trigger_code:
            if pressed and self.hotkey.modifiers <= self._pressed_mods:
                self.on_activate()
            elif not pressed:
                self.on_deactivate()

    def start(self) -> None:
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2)
            self._thread = None

    def join(self) -> None:
        if self._thread is not None:
            self._thread.join()


def is_wayland() -> bool:
    return os.environ.get("XDG_SESSION_TYPE", "").lower() == "wayland" or bool(
        os.environ.get("WAYLAND_DISPLAY")
    )


def make_listener(kind: str, hotkey: Hotkey, on_activate, on_deactivate):
    """kind: 'auto' | 'pynput' | 'evdev'."""
    if kind == "auto":
        kind = "evdev" if is_wayland() else "pynput"
    if kind == "pynput":
        return PynputListener(hotkey, on_activate, on_deactivate)
    if kind == "evdev":
        return EvdevListener(hotkey, on_activate, on_deactivate)
    raise ValueError(f"Unknown listener: {kind!r} (expected auto, pynput, or evdev)")
