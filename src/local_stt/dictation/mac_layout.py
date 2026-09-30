"""pynput reads the keyboard layout through Text Input Sources. Once a window
with a text field is open, macOS traps the process when those calls run off
the main thread, and the tray starts dictation on a worker thread. So the
layout is read once on the main thread and pynput reuses that copy. A layout
switched to later takes effect after a restart.
"""

from __future__ import annotations

import contextlib
import threading

_layout = None


def use_snapshot() -> None:
    """Idempotent. The first call must run on the main thread."""
    global _layout
    if _layout is not None:
        return
    if threading.current_thread() is not threading.main_thread():
        raise RuntimeError("the keyboard layout has to be read on the main thread first")

    import pynput._util.darwin as util
    import pynput.keyboard._darwin as keyboard

    with util.keycode_context() as layout:
        _layout = layout

    @contextlib.contextmanager
    def snapshot():
        yield _layout

    util.keycode_context = snapshot  # used by get_unicode_to_keycode_map()
    keyboard.keycode_context = snapshot  # used by Listener._run()
