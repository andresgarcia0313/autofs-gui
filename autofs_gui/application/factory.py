from __future__ import annotations

from typing import Optional, Callable

from autofs_gui.application.use_cases import UseCases, Paths
from autofs_gui.infrastructure.system import (
    CommandRunner,
    FileSystemGateway,
    MASTER_D_PATH,
    MAP_FILE_PATH,
    FUSE_CONF,
)


def make_usecases(ask_pass: Optional[Callable[[], Optional[str]]] = None) -> UseCases:
    """Factory helper para construir UseCases con dependencias reales."""
    return UseCases(
        CommandRunner,
        FileSystemGateway,
        Paths(MASTER_D_PATH, MAP_FILE_PATH, FUSE_CONF),
        ask_pass=ask_pass,
    )

