"""Linux tray shell: Ayatana AppIndicator via the system PyGObject, put on
sys.path after the venv's packages, since the venv has no `gi`."""

from __future__ import annotations

import logging
import os
import signal
import sys

from ..desktop import open_target
from .icons import ensure_icons, icon_name

log = logging.getLogger(__name__)

_SYSTEM_SITE = "/usr/lib/python3/dist-packages"


def _load_gi():
    """Make the system PyGObject importable from the venv. Appended (not
    prepended) so venv packages keep priority over system ones."""
    if _SYSTEM_SITE not in sys.path and os.path.isdir(_SYSTEM_SITE):
        sys.path.append(_SYSTEM_SITE)
    import gi

    gi.require_version("Gtk", "3.0")
    gi.require_version("AyatanaAppIndicator3", "0.1")
    from gi.repository import AyatanaAppIndicator3, GLib, Gtk

    return Gtk, GLib, AyatanaAppIndicator3


class GtkShell:
    def __init__(self):
        self._gtk, self._glib, self._appindicator = _load_gi()
        self._indicator = None
        self._items: list[tuple] = []  # (menu item, label function)

    def build(self, rows) -> None:
        Gtk, AppIndicator = self._gtk, self._appindicator
        icon_dir = ensure_icons()
        self._indicator = AppIndicator.Indicator.new(
            "local-stt",
            icon_name("off"),
            AppIndicator.IndicatorCategory.APPLICATION_STATUS,
        )
        self._indicator.set_icon_theme_path(str(icon_dir))
        self._indicator.set_status(AppIndicator.IndicatorStatus.ACTIVE)
        self._indicator.set_title("local-stt")

        menu = Gtk.Menu()
        for row in rows:
            if row is None:
                menu.append(Gtk.SeparatorMenuItem())
                continue
            label, handler = row
            mi = Gtk.MenuItem(label=label() or "")
            mi.connect("activate", lambda *_, h=handler: h())
            menu.append(mi)
            self._items.append((mi, label))
        menu.show_all()
        self._refresh()
        self._indicator.set_menu(menu)
        log.info("tray running (AppIndicator)")

    # GTK is not thread-safe; everything below marshals onto the main loop

    def set_state(self, state: str) -> None:
        self._glib.idle_add(self._indicator.set_icon_full, icon_name(state), state)

    def refresh(self) -> None:
        self._glib.idle_add(self._refresh)

    def _refresh(self) -> None:
        for mi, label in self._items:
            title = label()
            mi.set_visible(title is not None)
            if title is not None:
                mi.set_label(title)

    def show_page(self, url: str, title: str) -> None:
        open_target(url)

    def close_page(self) -> None:
        pass  # the page is a browser tab, which the page can't close

    def run(self, on_signal) -> None:
        """on_signal runs for Ctrl+C and SIGTERM (systemd stop)."""
        for signum in (signal.SIGINT, signal.SIGTERM):
            self._glib.unix_signal_add(
                self._glib.PRIORITY_DEFAULT, signum, lambda: on_signal() or False
            )
        self._gtk.main()

    def quit(self) -> None:
        self._glib.idle_add(self._gtk.main_quit)
