#!/usr/bin/env python3
import sys

if __name__ == "__main__":
    if len(sys.argv) == 1 or (len(sys.argv) > 1 and sys.argv[1].lower() == "gui"):
        if len(sys.argv) > 1:
            del sys.argv[1]
        from autofs_gui.presentation.gui import app
        app.run()
    else:
        from autofs_gui.presentation.cli import main
        raise SystemExit(main())
