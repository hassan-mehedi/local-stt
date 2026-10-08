"""macOS privacy permissions and start at login. Status is "granted", "denied",
"not_asked" or "unknown", for the app running stt (local-stt.app or a terminal)."""

from __future__ import annotations

import ctypes
import logging
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

from .desktop import app_bundle, open_target

log = logging.getLogger(__name__)

NAMES = ("microphone", "input_monitoring", "accessibility", "system_audio")

_PANES = {
    "microphone": "Privacy_Microphone",
    "input_monitoring": "Privacy_ListenEvent",
    "accessibility": "Privacy_Accessibility",
    "system_audio": "Privacy_AudioCapture",
}
_TEST_SOUND = "/System/Library/Sounds/Glass.aiff"

# macOS has no API to read the system audio permission, so it is known only
# after a test recording
_system_audio = "unknown"
_test_lock = threading.Lock()


def supported() -> bool:
    return sys.platform == "darwin"


def status() -> dict[str, str]:
    if not supported():
        return {}
    return {
        "microphone": _microphone(),
        "input_monitoring": _input_monitoring(),
        "accessibility": _accessibility(),
        "system_audio": _system_audio,
    }


def request(name: str) -> str:
    """Shows the system prompt if macOS hasn't asked yet, otherwise opens the
    System Settings pane, where a denied permission has to be switched on."""
    if name not in NAMES:
        raise ValueError(f"unknown permission {name!r}")
    current = status()[name]
    if name == "system_audio":
        return test_system_audio()
    if current == "not_asked":
        _prompt(name)
    elif current != "granted":
        open_settings(name)
    return status()[name]


def open_settings(name: str) -> None:
    open_target(f"x-apple.systempreferences:com.apple.preference.security?{_PANES[name]}")


def test_system_audio() -> str:
    """Plays a short sound and checks the system audio recording heard it.
    The first run is also what makes macOS ask for the permission."""
    global _system_audio
    from .audio.mac_audio import MacSystemAudioRecorder

    with _test_lock, tempfile.TemporaryDirectory() as tmp:
        recorder = MacSystemAudioRecorder(Path(tmp) / "test.wav")
        try:
            recorder.start()
            subprocess.run(["afplay", _TEST_SOUND], timeout=10)
            time.sleep(0.3)
            recorder.stop()
        except Exception:
            log.exception("system audio test failed")
            recorder.stop()
            _system_audio = "denied"
            return _system_audio
        _system_audio = "granted" if recorder.peak else "denied"
    return _system_audio


def _prompt(name: str) -> None:
    if name == "microphone":
        import AVFoundation

        AVFoundation.AVCaptureDevice.requestAccessForMediaType_completionHandler_(
            AVFoundation.AVMediaTypeAudio, lambda granted: None
        )
    elif name == "input_monitoring":
        import Quartz

        Quartz.CGRequestListenEventAccess()
    elif name == "accessibility":
        import HIServices

        HIServices.AXIsProcessTrustedWithOptions(
            {HIServices.kAXTrustedCheckOptionPrompt: True}
        )


def _microphone() -> str:
    import AVFoundation

    code = AVFoundation.AVCaptureDevice.authorizationStatusForMediaType_(
        AVFoundation.AVMediaTypeAudio
    )
    return {
        AVFoundation.AVAuthorizationStatusNotDetermined: "not_asked",
        AVFoundation.AVAuthorizationStatusAuthorized: "granted",
    }.get(code, "denied")


def _input_monitoring() -> str:
    # IOHIDCheckAccess, unlike CGPreflightListenEventAccess, tells "never
    # asked" apart from "denied"
    iokit = ctypes.cdll.LoadLibrary("/System/Library/Frameworks/IOKit.framework/IOKit")
    iokit.IOHIDCheckAccess.restype = ctypes.c_uint
    iokit.IOHIDCheckAccess.argtypes = [ctypes.c_uint]
    listen_event = 1  # kIOHIDRequestTypeListenEvent
    return {0: "granted", 1: "denied"}.get(iokit.IOHIDCheckAccess(listen_event), "not_asked")


def _accessibility() -> str:
    import HIServices

    # macOS can't say whether it asked before; an untrusted app that asks
    # again only gets the prompt, which leads to the same pane
    return "granted" if HIServices.AXIsProcessTrusted() else "not_asked"



def login_item() -> dict:
    """Start at login needs the app bundle; a source install uses the
    launchd agent in packaging/ instead."""
    if not supported() or app_bundle() is None:
        return {"supported": False, "enabled": False}
    import ServiceManagement as SM

    code = SM.SMAppService.mainAppService().status()
    return {
        "supported": True,
        "enabled": code == SM.SMAppServiceStatusEnabled,
        "needs_approval": code == SM.SMAppServiceStatusRequiresApproval,
    }


def set_login_item(enabled: bool) -> dict:
    if not login_item()["supported"]:
        raise ValueError("start at login needs local-stt.app")
    import ServiceManagement as SM

    service = SM.SMAppService.mainAppService()
    ok, error = (service.registerAndReturnError_ if enabled else service.unregisterAndReturnError_)(None)
    if not ok:
        raise RuntimeError(f"start at login: {error.localizedDescription()}")
    return login_item()
