from __future__ import annotations
import shlex
from typing import Dict, Any


def build_ssh_test_cmd(entry: Dict[str, Any], check_path: bool = True, timeout_sec: int = 10) -> str:
    user = (entry.get("user") or "").strip()
    host = (entry.get("host") or "").strip()
    remote_path = (entry.get("remote_path") or "").strip()
    identity_file = (entry.get("identity_file") or "").strip()
    sai = str(entry.get("server_alive_interval", "")).strip()
    sac = str(entry.get("server_alive_count", "")).strip()

    if not host:
        raise ValueError("Host vacío en la entrada.")

    dest = f"{user+'@' if user else ''}{host}"
    tokens = [
        "ssh",
        "-o", "BatchMode=yes",
        "-o", f"ConnectTimeout={int(timeout_sec)}",
        "-o", "StrictHostKeyChecking=accept-new",
    ]
    if sai:
        tokens += ["-o", f"ServerAliveInterval={sai}"]
    if sac:
        tokens += ["-o", f"ServerAliveCountMax={sac}"]
    if identity_file:
        tokens += ["-i", identity_file]
    tokens.append(dest)

    if check_path:
        rcmd = f"test -e {shlex.quote(remote_path)} && echo __PATH_OK__ || echo __PATH_MISSING__"
    else:
        rcmd = "echo __CONNECT_OK__"
    tokens.append(rcmd)

    return " ".join(shlex.quote(t) for t in tokens)

