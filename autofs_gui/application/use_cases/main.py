from __future__ import annotations
from typing import Tuple, List, Dict, Any, Optional, Callable

from autofs_gui.application.ports import CommandsPort, FilesPort
from autofs_gui.domain.services import build_master_file as build_master_text, build_map_file
from autofs_gui.infrastructure.parsers import parse_map_text
from autofs_gui.infrastructure.ssh import build_ssh_test_cmd
from autofs_gui.infrastructure.system import run_sudo
from .paths import Paths


# Simple shell-quote helper without importing shlex in UI
def shlex_quote(s: str) -> str:
    from shlex import quote as _q
    return _q(s or "")


class UseCases:
    def __init__(self, runner: CommandsPort, files: FilesPort, paths: Paths, ask_pass: Optional[Callable[[], Optional[str]]] = None):
        self.runner = runner
        self.files = files
        self.paths = paths
        self.ask_pass = ask_pass

    def build_files(self, entries: List[Dict[str, Any]], timeout: int, ghost: bool) -> Tuple[str, str]:
        master_body = build_master_text(self.paths.MAP_FILE_PATH, timeout, ghost)
        map_body = build_map_file(entries)
        return master_body, map_body

    def read_current_files(self) -> Tuple[str, str]:
        return (
            self.files.read(self.paths.MASTER_D_PATH) or "",
            self.files.read(self.paths.MAP_FILE_PATH) or "",
        )

    def parse_master_options(self, master_txt: str) -> Tuple[int, bool]:
        ghost = "--ghost" in (master_txt or "")
        to = 120
        for tok in (master_txt or "").split():
            if tok.startswith("--timeout="):
                try:
                    to = int(tok.split("=", 1)[1])
                except Exception:
                    pass
        return to, ghost

    def load_from_system(self) -> Tuple[List[Dict[str, Any]], int, bool]:
        master_txt = self.files.read(self.paths.MASTER_D_PATH) or ""
        map_txt = self.files.read(self.paths.MAP_FILE_PATH) or ""
        entries = parse_map_text(map_txt) if map_txt else []
        timeout, ghost = self.parse_master_options(master_txt) if master_txt else (120, True)
        return entries, timeout, ghost

    def service_cmd(self, action: str) -> str:
        if action == "status":
            return "systemctl status autofs --no-pager"
        return f"systemctl {action} autofs"

    def enable_user_allow_other(self, fuse_conf_path: str) -> None:
        txt = self.files.read(fuse_conf_path) or ""
        if txt and "user_allow_other" in txt:
            new = txt.replace("#user_allow_other", "user_allow_other")
        else:
            new = (txt + "\n" if txt else "") + "user_allow_other\n"
        # Direct write first; if fails, elevate via sudo copy
        try:
            self.files.write_atomic(fuse_conf_path, new)
            return
        except Exception:
            tmp = "/tmp/fuse.conf.user_allow_other"
            self.files.write_atomic(tmp, new)
            rc, out, err = run_sudo(f"cp {shlex_quote(tmp)} {shlex_quote(fuse_conf_path)}", timeout=20, ask_pass=self.ask_pass)
            if rc != 0:
                raise PermissionError(err or "sudo copy failed")

    def ssh_test_cmd(self, entry: Dict[str, Any], check_path: bool = True, timeout_sec: int = 10) -> str:
        return build_ssh_test_cmd(entry, check_path=check_path, timeout_sec=timeout_sec)

    # Convenience wrappers that execute via runner
    def service(self, action: str, timeout: int = 30) -> Tuple[int, str, str]:
        cmd = self.service_cmd(action)
        if action == "status":
            return self.runner.run(cmd, timeout)
        return run_sudo(cmd, timeout=timeout, ask_pass=self.ask_pass)

    def test_ls(self, path: str, timeout: int = 30) -> Tuple[int, str, str]:
        return self.runner.run(f"ls -la {shlex_quote(path)}", timeout)

    def umount(self, path: str, timeout: int = 30) -> Tuple[int, str, str]:
        return self.runner.run(f"umount -f {shlex_quote(path)}", timeout)

    def ssh_test(self, entry: Dict[str, Any], check_path: bool = True, timeout_sec: int = 10) -> Tuple[int, str, str]:
        cmd = self.ssh_test_cmd(entry, check_path=check_path, timeout_sec=timeout_sec)
        return self.runner.run(cmd, max(timeout_sec + 10, 20))

    def check_mount(self, path: str, timeout: int = 10) -> Tuple[int, str, str]:
        return self.runner.run(f"mountpoint {shlex_quote(path)}", timeout)

    def ensure_root_access(self, entry: Dict[str, Any]) -> Optional[str]:
        host = (entry.get("host") or "").strip()
        remote_user = (entry.get("user") or "").strip()
        user_identity = (entry.get("identity_file") or "").strip()
        if not host or not remote_user or not user_identity:
            return None

        root_identity = "/root/.ssh/id_ed25519"
        setup_cmds = [
            "install -d -m 700 /root/.ssh",
            "touch /root/.ssh/known_hosts",
            "chmod 600 /root/.ssh/known_hosts",
            "test -f /root/.ssh/id_ed25519 || ssh-keygen -q -t ed25519 -N '' -f /root/.ssh/id_ed25519",
        ]
        for cmd in setup_cmds:
            rc, out, err = run_sudo(cmd, timeout=20, ask_pass=self.ask_pass)
            if rc != 0:
                raise RuntimeError(err or out or f"Fallo ejecutando: {cmd}")

        rc, pub, err = run_sudo("cat /root/.ssh/id_ed25519.pub", timeout=10, ask_pass=self.ask_pass)
        if rc != 0 or not (pub := (pub or "").strip()):
            raise RuntimeError(err or "No se pudo leer la clave pública de root.")

        escaped_pub = pub.replace("'", "'\"'\"'")
        remote = f"{remote_user}@{host}"
        remote_cmd = (
            "mkdir -p ~/.ssh && chmod 700 ~/.ssh && "
            "touch ~/.ssh/authorized_keys && chmod 600 ~/.ssh/authorized_keys && "
            f"(grep -qxF '{escaped_pub}' ~/.ssh/authorized_keys || echo '{escaped_pub}' >> ~/.ssh/authorized_keys)"
        )
        ssh_cmd = (
            f"ssh -o StrictHostKeyChecking=accept-new "
            f"-i {shlex_quote(user_identity)} {shlex_quote(remote)} {shlex_quote(remote_cmd)}"
        )
        rc, out, err = self.runner.run(ssh_cmd, timeout=30)
        if rc != 0:
            raise RuntimeError(err or out or "No se pudo registrar la clave de root en el servidor remoto.")

        return root_identity

    def trigger_mount(self, path: str, timeout: int = 20) -> Tuple[int, str, str]:
        return run_sudo(f"ls -la {shlex_quote(path)}", timeout=timeout, ask_pass=self.ask_pass)

    def collect_autofs_log(self, lines: int = 40) -> Tuple[int, str, str]:
        cmd = f"journalctl -u autofs -n {lines} --no-pager"
        return run_sudo(cmd, timeout=20, ask_pass=self.ask_pass)

    def write_config(self, master_body: str, map_body: str, as_root: bool) -> Dict[str, Any]:
        if as_root:
            self.files.write_atomic(self.paths.MASTER_D_PATH, master_body)
            self.files.write_atomic(self.paths.MAP_FILE_PATH, map_body)
            return {
                "temporary": False,
                "paths": (self.paths.MASTER_D_PATH, self.paths.MAP_FILE_PATH),
                "message": f"Configuración guardada en sistema.\n\n{self.paths.MASTER_D_PATH}\n{self.paths.MAP_FILE_PATH}",
            }
        # Try sudo copy from /tmp
        tmp_master = "/tmp/sshfs-manager.autofs"
        tmp_map = "/tmp/auto.sshfs-manager"
        self.files.write_atomic(tmp_master, master_body)
        self.files.write_atomic(tmp_map, map_body)
        rc, out, err = run_sudo(
            f"cp {shlex_quote(tmp_master)} {shlex_quote(self.paths.MASTER_D_PATH)} && cp {shlex_quote(tmp_map)} {shlex_quote(self.paths.MAP_FILE_PATH)}",
            timeout=30,
            ask_pass=self.ask_pass,
        )
        if rc == 0:
            return {
                "temporary": False,
                "paths": (self.paths.MASTER_D_PATH, self.paths.MAP_FILE_PATH),
                "message": f"Configuración guardada en sistema.\n\n{self.paths.MASTER_D_PATH}\n{self.paths.MAP_FILE_PATH}",
            }
        instr = (
            f"No se pudo elevar privilegios automáticamente.\n\n"
            f"Se guardaron archivos de ejemplo en:\n"
            f"  {tmp_master}\n"
            f"  {tmp_map}\n\n"
            f"Para instalarlos manualmente:\n"
            f"  sudo cp {tmp_master} {self.paths.MASTER_D_PATH}\n"
            f"  sudo cp {tmp_map} {self.paths.MAP_FILE_PATH}\n"
            f"  sudo systemctl restart autofs\n"
        )
        return {"temporary": True, "paths": (tmp_master, tmp_map), "message": instr}
