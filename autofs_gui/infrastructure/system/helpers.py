from __future__ import annotations
import os

def is_root() -> bool:
    try:
        return os.geteuid() == 0
    except AttributeError:
        return False
