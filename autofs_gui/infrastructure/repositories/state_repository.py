from __future__ import annotations
import os
import json
from typing import Dict, Any

APP_CONFIG_DIR = os.path.expanduser("~/.config/autofs_manager")
APP_CONFIG_FILE = os.path.join(APP_CONFIG_DIR, "state.json")


def ensure_config_dir() -> None:
    os.makedirs(APP_CONFIG_DIR, exist_ok=True)


def load_state() -> Dict[str, Any]:
    ensure_config_dir()
    if os.path.exists(APP_CONFIG_FILE):
        try:
            with open(APP_CONFIG_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def save_state(data: Dict[str, Any]) -> None:
    ensure_config_dir()
    with open(APP_CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

