from __future__ import annotations
from typing import Protocol, Dict, Any


class StatePort(Protocol):
    def load(self) -> Dict[str, Any]:
        ...

    def save(self, data: Dict[str, Any]) -> None:
        ...
