from __future__ import annotations
from dataclasses import dataclass, asdict
from typing import Dict, Any


@dataclass
class SshfsEntry:
    mount_point: str
    host: str
    remote_path: str
    user: str = ""
    fstype: str = "fuse.sshfs"
    identity_file: str = ""
    allow_other: bool = True
    uid: str = "1000"
    gid: str = "1000"
    umask: str = "022"
    server_alive_interval: int = 15
    server_alive_count: int = 3
    reconnect: bool = True
    delay_connect: bool = True
    extra_options: str = ""

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "SshfsEntry":
        return SshfsEntry(**d)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
