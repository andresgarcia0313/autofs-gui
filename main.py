#!/usr/bin/env python3
import os
import sys


def ensure_root():
    if os.name != "posix":
        return
    geteuid = getattr(os, "geteuid", None)
    if geteuid is None or geteuid() == 0:
        return

    script = os.path.abspath(__file__)
    args = [sys.executable, script] + sys.argv[1:]
    try:
        os.execvp("sudo", ["sudo", "-E"] + args)
    except OSError as exc:
        print(f"No se pudo elevar privilegios automáticamente: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    ensure_root()
    if len(sys.argv) == 1 or (len(sys.argv) > 1 and sys.argv[1].lower() == "gui"):
        if len(sys.argv) > 1:
            del sys.argv[1]
        from autofs_gui.presentation.gui import app

        app.run()
    else:
        from autofs_gui.presentation.cli import main

        raise SystemExit(main())
