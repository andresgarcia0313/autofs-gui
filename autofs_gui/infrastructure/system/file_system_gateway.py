from __future__ import annotations
import os


class FileSystemGateway:
    @staticmethod
    def read_file(path: str) -> str | None:
        try:
            with open(path, "r", encoding="utf-8") as f:
                return f.read()
        except Exception:
            return None

    @staticmethod
    def write_file_atomic(path: str, content: str) -> None:
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(content)
        os.replace(tmp, path)

    # Ports compatibility (FilesPort)
    @staticmethod
    def read(path: str) -> str | None:
        return FileSystemGateway.read_file(path)

    @staticmethod
    def write_atomic(path: str, content: str) -> None:
        return FileSystemGateway.write_file_atomic(path, content)
