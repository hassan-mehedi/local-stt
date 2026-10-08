"""Native window for a settings server page (onboarding, settings); main thread
only. While open the app shows in the Dock so the window can't get lost."""

from __future__ import annotations

from AppKit import (
    NSApplication,
    NSApplicationActivationPolicyAccessory,
    NSApplicationActivationPolicyRegular,
    NSBackingStoreBuffered,
    NSMakeRect,
    NSMenu,
    NSMenuItem,
    NSViewHeightSizable,
    NSViewWidthSizable,
    NSWindow,
    NSWindowStyleMaskClosable,
    NSWindowStyleMaskMiniaturizable,
    NSWindowStyleMaskResizable,
    NSWindowStyleMaskTitled,
)
from Foundation import NSURL, NSObject, NSURLRequest
from WebKit import WKWebView, WKWebViewConfiguration


class _WindowDelegate(NSObject):
    def windowWillClose_(self, notification):
        NSApplication.sharedApplication().setActivationPolicy_(
            NSApplicationActivationPolicyAccessory
        )


class PageWindow:
    def __init__(self, width: int = 640, height: int = 720):
        style = (
            NSWindowStyleMaskTitled | NSWindowStyleMaskClosable
            | NSWindowStyleMaskMiniaturizable | NSWindowStyleMaskResizable
        )
        self._window = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(0, 0, width, height), style, NSBackingStoreBuffered, False
        )
        self._window.setReleasedWhenClosed_(False)
        self._window.setMinSize_((480, 480))
        self._delegate = _WindowDelegate.alloc().init()
        self._window.setDelegate_(self._delegate)
        self._web = WKWebView.alloc().initWithFrame_configuration_(
            self._window.contentView().bounds(), WKWebViewConfiguration.alloc().init()
        )
        self._web.setAutoresizingMask_(NSViewWidthSizable | NSViewHeightSizable)
        self._window.setContentView_(self._web)
        self._window.center()

    def show(self, url: str, title: str) -> None:
        self._window.setTitle_(title)
        self._web.loadRequest_(NSURLRequest.requestWithURL_(NSURL.URLWithString_(url)))
        app = NSApplication.sharedApplication()
        app.setActivationPolicy_(NSApplicationActivationPolicyRegular)
        self._window.makeKeyAndOrderFront_(None)
        app.activateIgnoringOtherApps_(True)

    def close(self) -> None:
        self._window.performClose_(None)


def install_main_menu() -> None:
    """An app menu and Edit menu. The menu bar never shows them for a menu
    bar app, but Cmd+C/V/X/A/Z and Cmd+W in the window go through them."""

    def menu(title: str, items: list[tuple[str, str, str]]) -> NSMenuItem:
        sub = NSMenu.alloc().initWithTitle_(title)
        for label, action, key in items:
            sub.addItemWithTitle_action_keyEquivalent_(label, action, key)
        holder = NSMenuItem.alloc().init()
        holder.setSubmenu_(sub)
        return holder

    main = NSMenu.alloc().init()
    main.addItem_(menu("local-stt", [
        ("Close Window", "performClose:", "w"),
        ("Hide local-stt", "hide:", "h"),
    ]))
    edit = menu("Edit", [
        ("Undo", "undo:", "z"),
        ("Cut", "cut:", "x"),
        ("Copy", "copy:", "c"),
        ("Paste", "paste:", "v"),
        ("Select All", "selectAll:", "a"),
    ])
    # an uppercase key equivalent means Shift+Cmd
    edit.submenu().insertItemWithTitle_action_keyEquivalent_atIndex_("Redo", "redo:", "Z", 1)
    main.addItem_(edit)
    NSApplication.sharedApplication().setMainMenu_(main)
