from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass
from typing import Iterable, List, Optional, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed


@dataclass(frozen=True)
class HostCandidate:
    name: str
    address: Optional[str]
    source: str


_CACHE_LOCK = threading.Lock()
_CACHE: List[HostCandidate] = []
_CACHE_TS: float = 0.0
_CACHE_TTL = 60  # seconds


def _run_command(cmd: List[str], timeout: int = 5) -> Tuple[int, str, str]:
    if not cmd:
        return 1, "", "empty command"
    if not shutil.which(cmd[0]):
        return 127, "", f"{cmd[0]} not found"
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return 124, "", "timeout"
    except Exception as exc:
        return 1, "", str(exc)
    return proc.returncode, proc.stdout.strip(), proc.stderr.strip()


def _discover_mdns() -> List[HostCandidate]:
    cmd = ["avahi-browse", "-r", "-p", "_ssh._tcp"]
    rc, out, err = _run_command(cmd, timeout=8)
    if rc != 0 or not out:
        return []
    candidates: List[HostCandidate] = []
    for line in out.splitlines():
        # avahi-browse -p format: =;eth0;IPv4;hostname;_ssh._tcp;local;hostname.local;address;port;txt...
        parts = line.split(";")
        if len(parts) < 9:
            continue
        hostname = parts[3].strip()
        address = parts[7].strip() or None
        full = parts[6].strip() or hostname
        name = full.rstrip(".")
        candidates.append(HostCandidate(name=name, address=address, source="mDNS"))
    return candidates


def _discover_tailscale() -> List[HostCandidate]:
    cmd = ["tailscale", "status", "--json"]
    rc, out, err = _run_command(cmd, timeout=5)
    if rc != 0 or not out:
        return []
    try:
        data = json.loads(out)
    except json.JSONDecodeError:
        return []
    peers = data.get("Peer", {})
    candidates: List[HostCandidate] = []
    for peer in peers.values():
        dns_name = (peer.get("DNSName") or "").rstrip(".")
        host = peer.get("HostName") or dns_name
        if not host:
            continue
        ip = ""
        addrs = peer.get("TailscaleIPs") or []
        if addrs:
            ip = addrs[0]
        candidates.append(
            HostCandidate(
                name=dns_name or host,
                address=ip or None,
                source="Tailscale",
            )
        )
    return candidates


def _parse_known_hosts_file(path: str, source: str) -> Iterable[HostCandidate]:
    if not os.path.exists(path):
        return []
    candidates: List[HostCandidate] = []
    try:
        with open(path, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith("#") or line.startswith("|"):
                    continue
                parts = line.split()
                if not parts:
                    continue
                host_field = parts[0]
                hosts = host_field.split(",")
                for host in hosts:
                    host = host.strip().rstrip(".")
                    if host:
                        candidates.append(HostCandidate(name=host, address=None, source=source))
    except Exception:
        return []
    return candidates


def _discover_known_hosts() -> List[HostCandidate]:
    home = os.path.expanduser("~")
    candidates: List[HostCandidate] = []
    candidates.extend(_parse_known_hosts_file(os.path.join(home, ".ssh", "known_hosts"), "known_hosts"))
    candidates.extend(_parse_known_hosts_file("/root/.ssh/known_hosts", "root_known_hosts"))
    return candidates


def _discover_etc_hosts() -> List[HostCandidate]:
    path = "/etc/hosts"
    if not os.path.exists(path):
        return []
    candidates: List[HostCandidate] = []
    try:
        with open(path, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                parts = re.split(r"\s+", line)
                if len(parts) < 2:
                    continue
                address, *names = parts
                for name in names:
                    if name:
                        candidates.append(HostCandidate(name=name.rstrip("."), address=address, source="/etc/hosts"))
    except Exception:
        return []
    return candidates


def _discover_getent_hosts() -> List[HostCandidate]:
    cmd = ["getent", "hosts"]
    rc, out, err = _run_command(cmd, timeout=5)
    if rc != 0 or not out:
        return []
    candidates: List[HostCandidate] = []
    for line in out.splitlines():
        parts = re.split(r"\s+", line.strip())
        if len(parts) < 2:
            continue
        address, *names = parts
        for name in names:
            if name:
                candidates.append(HostCandidate(name=name.rstrip("."), address=address, source="getent"))
    return candidates


_DISCOVERY_FUNCS = [
    _discover_mdns,
    _discover_tailscale,
    _discover_known_hosts,
    _discover_etc_hosts,
    _discover_getent_hosts,
]


def discover_hosts(force: bool = False) -> List[HostCandidate]:
    global _CACHE, _CACHE_TS
    with _CACHE_LOCK:
        if not force and _CACHE and (time.time() - _CACHE_TS) < _CACHE_TTL:
            return list(_CACHE)

    results: List[HostCandidate] = []
    seen: set[Tuple[str, Optional[str]]] = set()
    with ThreadPoolExecutor(max_workers=len(_DISCOVERY_FUNCS)) as executor:
        futures = {executor.submit(func): func for func in _DISCOVERY_FUNCS}
        for future in as_completed(futures):
            try:
                candidates = future.result() or []
            except Exception:
                candidates = []
            for cand in candidates:
                key = (cand.name.lower(), cand.address)
                if key in seen:
                    continue
                seen.add(key)
                results.append(cand)

    results.sort(key=lambda c: (0 if c.source.lower() == "tailscale" else 1, c.source, c.name))
    with _CACHE_LOCK:
        _CACHE = results
        _CACHE_TS = time.time()
    return list(results)
