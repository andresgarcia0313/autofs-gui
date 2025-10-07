from __future__ import annotations
import os
from typing import Iterable, Dict, Any


def escape_spaces(path: str) -> str:
    return path.replace(" ", r"\040")


def build_master_file(map_file_path: str, timeout: int = 120, ghost: bool = True) -> str:
    opts = [f"--timeout={int(timeout)}"]
    if ghost:
        opts.append("--ghost")
    body = f"/- {map_file_path} {' '.join(opts)}\n"
    header = (
        "# Managed by Autofs Manager GUI (SSHFS)\n"
        "# This file is auto-generated. Edit via the GUI or your changes may be overwritten.\n"
    )
    return header + body


def build_map_line(entry: Dict[str, Any]) -> str:
    mount_point = (entry.get("mount_point") or "").strip()
    user = (entry.get("user") or "").strip()
    host = (entry.get("host") or "").strip()
    remote_path = (entry.get("remote_path") or "").strip()
    fstype = (entry.get("fstype") or "fuse.sshfs").strip() or "fuse.sshfs"
    identity_file = (entry.get("identity_file") or "").strip()
    uid = (entry.get("uid") or "").strip()
    gid = (entry.get("gid") or "").strip()
    umask = (entry.get("umask") or "").strip()
    allow_other = bool(entry.get("allow_other", False))
    reconnect = bool(entry.get("reconnect", True))
    delay_connect = bool(entry.get("delay_connect", True))
    sai = str(entry.get("server_alive_interval", "15")).strip()
    sac = str(entry.get("server_alive_count", "3")).strip()
    extra = (entry.get("extra_options") or "").strip()

    if not mount_point or not host or not remote_path:
        raise ValueError("Faltan campos: punto de montaje, host y/o ruta remota.")

    opts = [f"-fstype={fstype}"]
    if identity_file:
        opts.append(f"IdentityFile={identity_file}")
        if identity_file.startswith("/root/"):
            known_hosts = "/root/.ssh/known_hosts"
        else:
            ssh_dir = os.path.dirname(identity_file)
            known_hosts_candidate = os.path.join(ssh_dir, "known_hosts")
            known_hosts = known_hosts_candidate if os.path.exists(known_hosts_candidate) else None
        if known_hosts:
            opts.append(f"UserKnownHostsFile={known_hosts}")
        opts.append("StrictHostKeyChecking=accept-new")
    if allow_other:
        opts.append("allow_other")
    if uid:
        opts.append(f"uid={uid}")
    if gid:
        opts.append(f"gid={gid}")
    if umask:
        opts.append(f"umask={umask}")
    if sai:
        opts.append(f"ServerAliveInterval={sai}")
    if sac:
        opts.append(f"ServerAliveCountMax={sac}")
    if reconnect:
        opts.append("reconnect")
    if delay_connect:
        opts.append("delay_connect")
    if extra:
        for tok in extra.split(","):
            tok = tok.strip()
            if tok:
                opts.append(tok)

    remote_spec = f":{user + '@' if user else ''}{host}:{escape_spaces(remote_path)}"
    return f"{mount_point} {','.join(opts)} {remote_spec}"


def build_map_file(entries: Iterable[Dict[str, Any]]) -> str:
    header = (
        "# Managed by Autofs Manager GUI (SSHFS)\n"
        "# Each line maps a local path to a remote SSHFS target with options.\n"
        "# Format:\n"
        "# /local/mount -fstype=fuse.sshfs,IdentityFile=/home/user/.ssh/id_ed25519,allow_other,uid=1000,gid=1000,umask=022,ServerAliveInterval=15,ServerAliveCountMax=3,reconnect,delay_connect :user@host:/remote/path\n\n"
    )
    lines = [build_map_line(e) for e in entries]
    return header + "\n".join(lines) + ("\n" if lines else "")
