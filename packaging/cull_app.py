"""Entry point for the packaged app (PyInstaller needs a script, not a module)."""
import multiprocessing
import sys

from cull.desktop import main

if __name__ == "__main__":
    multiprocessing.freeze_support()
    sys.exit(main())
