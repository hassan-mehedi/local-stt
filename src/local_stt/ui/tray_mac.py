"""macOS menu bar shell: an AppKit status item with SF Symbol icons.
set_state() and refresh() hop to the main thread, as AppKit requires."""

from __future__ import annotations

import logging
import signal

from AppKit import (
    NSApplication,
    NSApplicationActivationPolicyAccessory,
    NSColor,
    NSEvent,
    NSEventTypeApplicationDefined,
    NSImage,
    NSImageSymbolConfiguration,
    NSMenu,
    NSMenuItem,
    NSStatusBar,
    NSVariableStatusItemLength,
)
from Foundation import NSObject
from PyObjCTools import AppHelper

from ..dictation.mac_layout import use_snapshot
from .window_mac import PageWindow, install_main_menu

log = logging.getLogger(__name__)

# state -> (SF Symbol, color); None renders as a template image, which
# follows the menu bar's own light/dark color
ICONS = {
    "off": ("mic.slash", None),
    "idle": ("mic", None),
    "recording": ("mic.fill", "systemRedColor"),
    "transcribing": ("waveform", "systemOrangeColor"),
}


class _MenuTarget(NSObject):
    """Receives menu clicks; each item's tag indexes into self.handlers."""

    def clicked_(self, sender):
        try:
            self.handlers[sender.tag()]()
        except Exception:
            log.exception("menu action failed")


class MacShell:
    def __init__(self):
        self._app = NSApplication.sharedApplication()
        # menu bar only: no Dock icon, no app switcher entry
        self._app.setActivationPolicy_(NSApplicationActivationPolicyAccessory)
        self._status_item = None
        self._target = None
        self._items: list[tuple] = []  # (NSMenuItem, label function)
        self._window = None

    def build(self, rows) -> None:
        self._status_item = NSStatusBar.systemStatusBar().statusItemWithLength_(
            NSVariableStatusItemLength
        )
        self._target = _MenuTarget.alloc().init()
        self._target.handlers = []

        menu = NSMenu.alloc().init()
        menu.setAutoenablesItems_(False)
        for row in rows:
            if row is None:
                menu.addItem_(NSMenuItem.separatorItem())
                continue
            label, handler = row
            item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
                label() or "", "clicked:", ""
            )
            item.setHidden_(label() is None)
            item.setTarget_(self._target)
            item.setTag_(len(self._target.handlers))
            self._target.handlers.append(handler)
            menu.addItem_(item)
            self._items.append((item, label))
        self._status_item.setMenu_(menu)
        install_main_menu()
        use_snapshot()  # dictation starts on a worker thread
        self._set_state("off")
        log.info("menu bar app running")

    def set_state(self, state: str) -> None:
        AppHelper.callAfter(self._set_state, state)

    def _set_state(self, state: str) -> None:
        symbol, tint = ICONS.get(state, ICONS["idle"])
        image = NSImage.imageWithSystemSymbolName_accessibilityDescription_(
            symbol, f"local-stt: {state}"
        )
        if tint:
            # contentTintColor leaves template images blank in the menu bar,
            # so bake the color into the symbol instead
            config = NSImageSymbolConfiguration.configurationWithPaletteColors_(
                [getattr(NSColor, tint)()]
            )
            image = image.imageWithSymbolConfiguration_(config)
        image.setTemplate_(tint is None)
        button = self._status_item.button()
        button.setImage_(image)
        button.setToolTip_(f"local-stt: {state}")

    def refresh(self) -> None:
        AppHelper.callAfter(self._refresh)

    def _refresh(self) -> None:
        for item, label in self._items:
            title = label()
            item.setHidden_(title is None)
            if title is not None:
                item.setTitle_(title)

    def show_page(self, url: str, title: str) -> None:
        AppHelper.callAfter(self._show_page, url, title)

    def _show_page(self, url: str, title: str) -> None:
        if self._window is None:
            self._window = PageWindow()
        self._window.show(url, title)

    def close_page(self) -> None:
        if self._window is not None:
            AppHelper.callAfter(self._window.close)

    def run(self, on_signal) -> None:
        """Python signal handlers can't fire while AppKit owns the main thread, so a
        Mach port wakes the run loop for Ctrl+C and launchd's SIGTERM."""
        from PyObjCTools import MachSignals

        for signum in (signal.SIGINT, signal.SIGTERM):
            MachSignals.signal(signum, lambda _signum: on_signal())
        self._app.run()

    def quit(self) -> None:
        AppHelper.callAfter(self._stop)

    def _stop(self) -> None:
        # stop_ only takes effect after the next event, so post one; this
        # returns from run() instead of terminate_, which exits the process
        # without running Python cleanup
        self._app.stop_(None)
        self._app.postEvent_atStart_(
            NSEvent.otherEventWithType_location_modifierFlags_timestamp_windowNumber_context_subtype_data1_data2_(
                NSEventTypeApplicationDefined, (0, 0), 0, 0, 0, None, 0, 0, 0
            ),
            True,
        )
