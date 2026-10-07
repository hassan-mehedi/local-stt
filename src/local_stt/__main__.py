"""`python -m local_stt`: the stt command line. With no arguments it runs
the menu bar app. The desktop app starts the engine as `-m local_stt engine`."""

import sys

from .cli import main

sys.exit(main(sys.argv[1:] or ["tray"]))
