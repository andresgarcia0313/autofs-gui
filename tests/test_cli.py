import json
import types
import importlib

from autofs_gui.presentation.cli.main import main
cli_module = importlib.import_module("autofs_gui.presentation.cli.main")
from autofs_gui.infrastructure.system.constants import MASTER_D_PATH, MAP_FILE_PATH


class FakeUseCases:
    def __init__(self):
        self.called = []
        self.service_responses = {}
        self.build_files_response = ("MASTER_TXT", "MAP_TXT")
        self.read_current_files_response = ("", "")
        self.load_from_system_response = ([], 120, True)
        self.write_config_response = {"temporary": False, "paths": (MASTER_D_PATH, MAP_FILE_PATH), "message": "OK"}
        self.ls_response = (0, "LS_OK", "")
        self.umount_response = (0, "UMOUNT_OK", "")
        self.ssh_response = (0, "SSH_OK", "")

    def service(self, action: str, timeout: int = 30):
        self.called.append(("service", action))
        return self.service_responses.get(action, (0, f"{action.upper()} OK", ""))

    def build_files(self, entries, timeout, ghost):
        self.called.append(("build_files", len(entries), timeout, ghost))
        return self.build_files_response

    def read_current_files(self):
        return self.read_current_files_response

    def load_from_system(self):
        return self.load_from_system_response

    def write_config(self, master_body: str, map_body: str, as_root: bool):
        self.called.append(("write_config", as_root))
        return self.write_config_response

    def ssh_test(self, entry, check_path=True, timeout_sec=10):
        self.called.append(("ssh_test", entry.get("host")))
        return self.ssh_response

    def test_ls(self, path, timeout=30):
        self.called.append(("ls", path))
        return self.ls_response

    def umount(self, path, timeout=30):
        self.called.append(("umount", path))
        return self.umount_response


def _patch_usecases(monkeypatch):
    uc = FakeUseCases()
    monkeypatch.setattr(cli_module, "make_usecases", lambda: uc)
    return uc


def test_service_status(monkeypatch, capsys):
    uc = _patch_usecases(monkeypatch)
    uc.service_responses["status"] = (0, "ACTIVE", "")
    rc = main(["service", "status"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "ACTIVE" in out


def test_load_prints_json(monkeypatch, capsys):
    uc = _patch_usecases(monkeypatch)
    uc.load_from_system_response = ([{"mount_point": "/mnt", "host": "h", "remote_path": "/r"}], 111, True)
    rc = main(["load"])
    captured = capsys.readouterr().out
    data = json.loads(captured)
    assert rc == 0
    assert data["master_timeout"] == 111
    assert data["entries"][0]["mount_point"] == "/mnt"


def test_build_no_write_prints_files(monkeypatch, capsys, tmp_path):
    uc = _patch_usecases(monkeypatch)
    uc.build_files_response = ("MASTER_CONTENT", "MAP_CONTENT")
    entries_path = tmp_path / "entries.json"
    entries_path.write_text(json.dumps([
        {"mount_point": "/mnt/x", "host": "h", "remote_path": "/r"}
    ]), encoding="utf-8")
    rc = main(["build", "--entries-json", str(entries_path)])
    out = capsys.readouterr().out
    assert rc == 0
    assert MASTER_D_PATH in out and MAP_FILE_PATH in out
    assert "MASTER_CONTENT" in out and "MAP_CONTENT" in out


def test_build_write_and_restart(monkeypatch, capsys, tmp_path):
    uc = _patch_usecases(monkeypatch)
    uc.write_config_response = {"temporary": False, "paths": (MASTER_D_PATH, MAP_FILE_PATH), "message": "WROTE"}
    uc.service_responses["restart"] = (0, "RESTARTED", "")
    entries_path = tmp_path / "entries.json"
    entries_path.write_text(json.dumps([
        {"mount_point": "/mnt/x", "host": "h", "remote_path": "/r"}
    ]), encoding="utf-8")
    rc = main(["build", "--entries-json", str(entries_path), "--write", "--restart"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "WROTE" in out
    assert "RESTARTED" in out


def test_ssh_check(monkeypatch, capsys):
    uc = _patch_usecases(monkeypatch)
    uc.ssh_response = (0, "__PATH_OK__", "")
    rc = main(["ssh-check", "--host", "h", "--remote-path", "/r"]) 
    out = capsys.readouterr().out
    assert rc == 0
    assert "__PATH_OK__" in out


def test_ls_and_umount(monkeypatch, capsys):
    uc = _patch_usecases(monkeypatch)
    uc.ls_response = (0, "LISTING", "")
    rc = main(["ls", "--path", "/tmp"]) 
    out = capsys.readouterr().out
    assert rc == 0 and "LISTING" in out

    uc.umount_response = (0, "UMOUNTED", "")
    rc = main(["umount", "--path", "/tmp"]) 
    out = capsys.readouterr().out
    assert rc == 0 and "UMOUNTED" in out

