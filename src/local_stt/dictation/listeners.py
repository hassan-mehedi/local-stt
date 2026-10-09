"""Hotkey listeners: pynput on X11 and macOS, evdev on Wayland. Callbacks run
for combo down, trigger up and Esc, and must not block."""

from __future__ import annotations

import logging
import os
import sys
import threading

from ..desktop import permission_hint
from .hotkey import Hotkey

log = logging.getLogger(__name__)

# a modifier on one side can be the trigger on its own, e.g. "alt_r"
SIDED_MODIFIERS = frozenset(
    f"{mod}_{side}" for mod in ("alt", "ctrl", "shift", "cmd") for side in "lr"
)


class PynputListener:
    def __init__(self, hotkey: Hotkey, on_activate, on_deactivate, on_cancel=None):
        self.hotkey = hotkey
        self.on_activate = on_activate
        self.on_deactivate = on_deactivate
        self.on_cancel = on_cancel
        self._pressed_mods: set[str] = set()
        self._trigger_down = False  # edge detection: X auto-repeat resends presses
        self._listener = None
        self._trigger_vks: frozenset[int] = frozenset()
        # macOS: key codes of the trigger, and whether the current press
        # fired the hotkey (its key events are then kept from the focused app)
        self._intercept_vks: frozenset[int] = frozenset()
        self._swallowing = False

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

        trigger = self.hotkey.trigger
        if trigger in SIDED_MODIFIERS:
            # compare values: on macOS Key.alt_l is an alias of Key.alt
            return isinstance(key, Key) and key.value == Key[trigger].value
        if self._trigger_vks and isinstance(key, KeyCode):
            return key.vk in self._trigger_vks  # canonical() drops the vk
        key = self._listener.canonical(key)
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
        from pynput.keyboard import Key

        if key == Key.esc and self.on_cancel is not None:
            self.on_cancel()
        if self._is_trigger(key):
            if self._trigger_down:
                return  # auto-repeat
            self._trigger_down = True
            if self.hotkey.modifiers <= self._pressed_mods:
                self._swallowing = bool(self._intercept_vks)
                self.on_activate()
            return
        mod = self._mod_name(key)
        if mod:
            self._pressed_mods.add(mod)

    def _on_release(self, key):
        if self._is_trigger(key):
            self._trigger_down = False
            self.on_deactivate()
            return
        mod = self._mod_name(key)
        if mod:
            self._pressed_mods.discard(mod)

    def start(self) -> None:
        from pynput import keyboard

        extra = {}
        listener_class = keyboard.Listener
        if sys.platform == "darwin":
            listener_class = _mac_key_listener()
            from .mac_layout import use_snapshot

            use_snapshot()
            _require_input_monitoring()
            trigger = self.hotkey.trigger
            if trigger in SIDED_MODIFIERS:
                pass  # never swallowed: a dropped modifier change leaves it stuck
            elif len(trigger) == 1:
                # Option changes the character a key types (Option+T is "†"),
                # so match the physical key instead
                self._trigger_vks = mac_keycodes(trigger)
                if not self._trigger_vks:
                    raise ValueError(
                        f"No key types {trigger!r} on the current keyboard layout"
                    )
                self._intercept_vks = self._trigger_vks
            elif trigger in keyboard.Key.__members__:
                self._intercept_vks = frozenset({keyboard.Key[trigger].value.vk})
            extra["darwin_intercept"] = self._darwin_intercept
        self._listener = listener_class(
            on_press=self._on_press, on_release=self._on_release, **extra
        )
        self._listener.start()
        self._listener.wait()
        # pynput's thread returns without an error when macOS refuses the event tap
        self._listener.join(0.3)
        if not self._listener.is_alive():
            self._listener = None
            raise RuntimeError(
                "macOS refused to let local-stt read the shortcut. "
                + permission_hint("Accessibility and Input Monitoring")
            )

    def _darwin_intercept(self, event_type, event):
        """Runs after the press/release callbacks. Returning None drops the
        event, so Option+Shift+T doesn't also type "ˇ" into the focused app."""
        import Quartz

        if not self._swallowing or event_type not in (
            Quartz.kCGEventKeyDown, Quartz.kCGEventKeyUp
        ):
            return event
        vk = Quartz.CGEventGetIntegerValueField(event, Quartz.kCGKeyboardEventKeycode)
        if vk not in self._intercept_vks:
            return event
        if event_type == Quartz.kCGEventKeyUp:
            self._swallowing = False
        return None

    def stop(self) -> None:
        if self._listener is not None:
            self._listener.stop()
            self._listener = None

    def join(self) -> None:
        if self._listener is not None:
            self._listener.join()


def mac_keycodes(char: str) -> frozenset[int]:
    """Key codes that type `char` with no modifiers held (main row and keypad
    both type digits)."""
    from pynput._util.darwin import keycode_context, keycode_to_string

    with keycode_context() as context:
        return frozenset(
            code for code in range(128) if keycode_to_string(context, code) == char
        )


def _require_input_monitoring() -> None:
    import Quartz

    if Quartz.CGPreflightListenEventAccess():
        return
    Quartz.CGRequestListenEventAccess()  # shows the system prompt once
    raise RuntimeError("macOS blocks reading the shortcut. " + permission_hint("Input Monitoring"))


def _mac_key_listener():
    """pynput's Listener without media key events: it turns those into
    NSEvents on its own thread, and AppKit belongs to the main thread."""
    import Quartz
    from pynput import keyboard

    class KeyListener(keyboard.Listener):
        _EVENTS = (
            Quartz.CGEventMaskBit(Quartz.kCGEventKeyDown)
            | Quartz.CGEventMaskBit(Quartz.kCGEventKeyUp)
            | Quartz.CGEventMaskBit(Quartz.kCGEventFlagsChanged)
        )

    return KeyListener


class EvdevListener:
    """Kernel-level key listener for Wayland sessions."""

    _MODS = {
        "KEY_LEFTMETA": "super", "KEY_RIGHTMETA": "super",
        "KEY_LEFTCTRL": "ctrl", "KEY_RIGHTCTRL": "ctrl",
        "KEY_LEFTALT": "alt", "KEY_RIGHTALT": "alt",
        "KEY_LEFTSHIFT": "shift", "KEY_RIGHTSHIFT": "shift",
    }

    def __init__(self, hotkey: Hotkey, on_activate, on_deactivate, on_cancel=None):
        try:
            import evdev  # noqa: F401
        except ImportError:
            raise RuntimeError(
                "evdev is required for Wayland hotkeys. Install it with:\n"
                "  sudo apt install python3-dev\n"
                "  (then remove the evdev override from pyproject.toml and run)\n"
                "  uv sync --extra cuda --extra wayland\n"
                "  (a uv tool install also drops --overrides overrides.txt)"
            ) from None
        self.hotkey = hotkey
        self.on_activate = on_activate
        self.on_deactivate = on_deactivate
        self.on_cancel = on_cancel
        self._trigger_code = self._resolve_trigger(hotkey.trigger)
        self._pressed_mods: set[str] = set()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    @staticmethod
    def _resolve_trigger(trigger: str) -> int:
        from evdev import ecodes

        name = f"KEY_{trigger.upper()}"
        # pynput names (page_up) drop the underscore in evdev (KEY_PAGEUP)
        code = getattr(ecodes, name, None) or getattr(ecodes, name.replace("_", ""), None)
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
        if name == "KEY_ESC" and pressed and self.on_cancel is not None:
            self.on_cancel()
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


def make_listener(kind: str, hotkey: Hotkey, on_activate, on_deactivate, on_cancel=None):
    """kind: 'auto' | 'pynput' | 'evdev'."""
    if kind == "auto":
        kind = "evdev" if is_wayland() else "pynput"
    if kind == "pynput":
        return PynputListener(hotkey, on_activate, on_deactivate, on_cancel)
    if kind == "evdev":
        return EvdevListener(hotkey, on_activate, on_deactivate, on_cancel)
    raise ValueError(f"Unknown listener: {kind!r} (expected auto, pynput, or evdev)")
