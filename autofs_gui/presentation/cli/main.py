#!/usr/bin/env python3
from __future__ import annotations
import argparse
import json
import getpass
from typing import Any, Dict, List

from autofs_gui.application.factory import make_usecases as build_usecases
from autofs_gui.application.use_cases import UseCases
from autofs_gui.infrastructure.system import (
    MASTER_D_PATH,
    MAP_FILE_PATH,
    FUSE_CONF,
    is_root,
)
from autofs_gui.infrastructure.repositories import load_state


def make_usecases() -> UseCases:
    def ask():
        try:
            return getpass.getpass("Contraseña sudo: ")
        except Exception:
            return None
    return build_usecases(ask)


def cmd_service(args):
    use = make_usecases()
    rc, out, err = use.service(args.action)
    print(out)
    if err:
        print(err, end="\n")
    return rc


def cmd_load(args):
    use = make_usecases()
    entries, timeout, ghost = use.load_from_system()
    print(json.dumps({"entries": entries, "master_timeout": timeout, "master_ghost": ghost}, indent=2, ensure_ascii=False))
    return 0


def _resolve_entries(args) -> (List[Dict[str, Any]], int, bool):
    use = make_usecases()
    if args.from_state:
        st = load_state() or {}
        entries = st.get("entries", [])
        timeout = int(args.timeout) if args.timeout is not None else int(st.get("master_timeout", 120))
        ghost = bool(st.get("master_ghost", True)) if args.ghost is None else bool(args.ghost)
        return entries, timeout, ghost
    elif args.entries_json:
        with open(args.entries_json, "r", encoding="utf-8") as f:
            entries = json.load(f)
        timeout = int(args.timeout or 120)
        ghost = bool(args.ghost if args.ghost is not None else True)
        return entries, timeout, ghost
    else:
        entries, timeout, ghost = use.load_from_system()
        if args.timeout is not None:
            timeout = int(args.timeout)
        if args.ghost is not None:
            ghost = bool(args.ghost)
        return entries, timeout, ghost


def cmd_build(args):
    use = make_usecases()
    entries, timeout, ghost = _resolve_entries(args)
    master_body, map_body = use.build_files(entries, timeout, ghost)
    if args.write:
        res = use.write_config(master_body, map_body, as_root=is_root())
        print(res["message"]) 
        if args.restart and not res["temporary"]:
            rc, out, err = use.service("restart")
            print(out)
            if err:
                print(err)
            return rc
        return 0
    else:
        print("===", MASTER_D_PATH, "===")
        print(master_body)
        print("===", MAP_FILE_PATH, "===")
        print(map_body)
        return 0


def cmd_ssh_check(args):
    use = make_usecases()
    entry = {
        "user": args.user or "",
        "host": args.host,
        "remote_path": args.remote_path,
        "identity_file": args.identity_file or "",
        "server_alive_interval": args.sai or 15,
        "server_alive_count": args.sac or 3,
    }
    rc, out, err = use.ssh_test(entry, check_path=True, timeout_sec=args.timeout)
    print(out)
    if err:
        print(err)
    return rc


def cmd_ls(args):
    use = make_usecases()
    rc, out, err = use.test_ls(args.path)
    print(out)
    if err:
        print(err)
    return rc


def cmd_umount(args):
    use = make_usecases()
    rc, out, err = use.umount(args.path)
    print(out)
    if err:
        print(err)
    return rc


def main(argv=None):
    p = argparse.ArgumentParser(prog="autofs-gui-cli", description="CLI para gestionar autofs (SSHFS)")
    sp = p.add_subparsers(dest="cmd", required=True)

    ps = sp.add_parser("service", help="Control del servicio autofs")
    ps.add_argument("action", choices=["status","start","stop","restart","enable","disable"])    
    ps.set_defaults(func=cmd_service)

    pl = sp.add_parser("load", help="Cargar configuración desde /etc (archivos gestionados)")
    pl.set_defaults(func=cmd_load)

    pb = sp.add_parser("build", help="Construir archivos y opcionalmente escribirlos")
    pb.add_argument("--from-state", action="store_true", help="Usar estado guardado del usuario")
    pb.add_argument("--entries-json", help="Ruta a JSON con 'entries' (lista de entradas)")
    pb.add_argument("--timeout", type=int, help="Timeout del master map")
    pb.add_argument("--ghost", type=lambda x: x.lower() in ("1","true","yes","y"), help="Usar --ghost")
    pb.add_argument("--write", action="store_true", help="Escribir a /etc (si root) o /tmp")
    pb.add_argument("--restart", action="store_true", help="Reiniciar autofs luego de escribir (si root)")
    pb.set_defaults(func=cmd_build)

    pssh = sp.add_parser("ssh-check", help="Probar conectividad SSH y existencia de ruta")
    pssh.add_argument("--host", required=True)
    pssh.add_argument("--user")
    pssh.add_argument("--remote-path", required=True)
    pssh.add_argument("--identity-file")
    pssh.add_argument("--timeout", type=int, default=10)
    pssh.add_argument("--sai", type=int, default=15)
    pssh.add_argument("--sac", type=int, default=3)
    pssh.set_defaults(func=cmd_ssh_check)

    pls = sp.add_parser("ls", help="Listar contenido de un punto de montaje")
    pls.add_argument("--path", required=True)
    pls.set_defaults(func=cmd_ls)

    pum = sp.add_parser("umount", help="Desmontar un punto de montaje (forzado)")
    pum.add_argument("--path", required=True)
    pum.set_defaults(func=cmd_umount)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
