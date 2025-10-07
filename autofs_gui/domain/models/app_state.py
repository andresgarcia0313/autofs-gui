from __future__ import annotations
from dataclasses import dataclass, field, asdict
from typing import List, Dict, Any

from .master_options import MasterOptions
from .sshfs_entry import SshfsEntry
from .ui_state import UIState


@dataclass
class AppState:
    entries: List[SshfsEntry] = field(default_factory=list)
    master_options: MasterOptions = field(default_factory=MasterOptions)
    ui: UIState = field(default_factory=UIState)

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "AppState":
        entries = [SshfsEntry.from_dict(x) for x in d.get("entries", [])]
        mo = MasterOptions(**d.get("master_options", {}))
        ui = UIState.from_dict(d.get("ui", {}))
        return AppState(entries=entries, master_options=mo, ui=ui)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "entries": [e.to_dict() for e in self.entries],
            "master_options": asdict(self.master_options),
            "ui": self.ui.to_dict(),
        }
