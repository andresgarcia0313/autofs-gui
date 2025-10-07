from __future__ import annotations
from dataclasses import dataclass, asdict
from typing import Dict, Any


@dataclass
class UIState:
    window_geometry: str | None = None
    active_tab: int = 0
    filter_query: str = ""
    ui_theme: str = "clam"

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "UIState":
        return UIState(**d)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
