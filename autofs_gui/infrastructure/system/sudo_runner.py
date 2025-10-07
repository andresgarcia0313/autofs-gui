from __future__ import annotations
import subprocess
from typing import Callable, Optional, Tuple

from .command_runner import CommandRunner

_CACHED_PASS: Optional[str] = None


def have_sudo_noninteractive() -> bool:
    rc, _, _ = CommandRunner.run("sudo -n true", timeout=5)
    return rc == 0


def run_sudo(cmd: str, timeout: int = 30, ask_pass: Optional[Callable[[], Optional[str]]] = None) -> Tuple[int, str, str]:
    # If sudo doesn't require password, use non-interactive
    if have_sudo_noninteractive():
        return CommandRunner.run(f"sudo -n bash -lc {sh_quote(cmd)}", timeout)

    global _CACHED_PASS
    attempts = 0
    while attempts < 2:
        attempts += 1
        passwd = _CACHED_PASS
        if not passwd and ask_pass:
            passwd = ask_pass() or ""
        if not passwd:
            # No password available
            return 1, "", "sudo password not provided"
        # Use sudo -S to read from stdin, suppress prompt with -p ''
        full = f"sudo -S -p '' bash -lc {sh_quote(cmd)}"
        try:
            proc = subprocess.run(full, input=passwd + "\n", shell=True, capture_output=True, text=True, timeout=timeout)
            out, err, rc = proc.stdout.strip(), proc.stderr.strip(), proc.returncode
        except subprocess.TimeoutExpired:
            return 124, "", f"Timeout executing: {cmd}"
        if rc == 0:
            _CACHED_PASS = passwd
            return rc, out, err
        # Detect wrong password and try again by clearing cache
        if "incorrect password" in err.lower() or "a password is required" in err.lower() or rc == 1:
            _CACHED_PASS = None
            # On next loop, ask again if possible
            continue
        return rc, out, err
    return 1, "", "sudo authentication failed"


def sh_quote(s: str) -> str:
    from shlex import quote as _q
    return _q(s or "")

