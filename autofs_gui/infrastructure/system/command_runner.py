from __future__ import annotations
import os
import subprocess
from typing import Tuple


class CommandRunner:
    @staticmethod
    def run(cmd: str, timeout: int = 15) -> Tuple[int, str, str]:
        try:
            proc = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
            return proc.returncode, proc.stdout.strip(), proc.stderr.strip()
        except subprocess.TimeoutExpired:
            return 124, "", f"Timeout executing: {cmd}"
