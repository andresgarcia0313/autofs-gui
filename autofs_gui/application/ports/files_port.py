from __future__ import annotations
from typing import Protocol, Optional


class FilesPort(Protocol):
    def read(self, path: str) -> Optional[str]:
        ...

    def write_atomic(self, path: str, content: str) -> None:
        ...
