from __future__ import annotations
from typing import Protocol, Tuple


class CommandsPort(Protocol):
    def run(self, cmd: str, timeout: int = 15) -> Tuple[int, str, str]:
        ...
