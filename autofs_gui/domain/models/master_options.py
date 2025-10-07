from __future__ import annotations
from dataclasses import dataclass


@dataclass
class MasterOptions:
    timeout: int = 120
    ghost: bool = True
