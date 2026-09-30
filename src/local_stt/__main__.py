"""`python -m local_stt`, and the entry point of the macOS app, which starts
with no arguments and so runs the menu bar app."""

import sys
from pathlib import Path

from .cli import main
from .desktop import app_bundle

if app_bundle() is not None and not sys.stderr.isatty():
    # opened from Finder: output would go nowhere, so keep a log
    log_path = Path.home() / "Library" / "Logs" / "local-stt.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    sys.stdout = sys.stderr = open(log_path, "a", buffering=1)

sys.exit(main(sys.argv[1:] or ["tray"]))
