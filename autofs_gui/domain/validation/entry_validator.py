from __future__ import annotations
from typing import Dict, Any


def validate_entry(entry: Dict[str, Any]) -> None:
    mp = (entry.get("mount_point") or "").strip()
    host = (entry.get("host") or "").strip()
    rpath = (entry.get("remote_path") or "").strip()
    if not mp:
        raise ValueError("El punto de montaje es obligatorio.")
    if not host:
        raise ValueError("El host es obligatorio.")
    if not rpath:
        raise ValueError("La ruta remota es obligatoria.")
    if not mp.startswith('/'):
        raise ValueError("El punto de montaje debe ser una ruta absoluta (empieza por '/').")
    if any(c.isspace() for c in host):
        raise ValueError("El host no debe contener espacios.")
    if not rpath.startswith('/'):
        raise ValueError("La ruta remota debería empezar por '/'.")

