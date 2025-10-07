from __future__ import annotations
from typing import List, Dict


def parse_map_text(map_txt: str) -> List[Dict]:
    new_entries: List[Dict] = []
    if not map_txt:
        return new_entries
    for line in map_txt.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        try:
            left, rest = line.split(" ", 1)
            opts_part, remote_part = rest.rsplit(" ", 1)
            if not opts_part.startswith("-fstype="):
                continue
            opt_items = opts_part.split(",")
            fstype = opt_items[0].split("=", 1)[1]
            opts = opt_items[1:]
            identity_file = ""
            allow_other = False
            uid = gid = umask = ""
            sai = sac = ""
            reconnect = delay_connect = False
            extra_opts: List[str] = []

            for o in opts:
                if "=" in o:
                    k, v = o.split("=", 1)
                    if k == "IdentityFile":
                        identity_file = v
                    elif k == "uid":
                        uid = v
                    elif k == "gid":
                        gid = v
                    elif k == "umask":
                        umask = v
                    elif k == "ServerAliveInterval":
                        sai = v
                    elif k == "ServerAliveCountMax":
                        sac = v
                    else:
                        extra_opts.append(o)
                else:
                    if o == "allow_other":
                        allow_other = True
                    elif o == "reconnect":
                        reconnect = True
                    elif o == "delay_connect":
                        delay_connect = True
                    else:
                        extra_opts.append(o)

            rp = remote_part[1:] if remote_part.startswith(":") else remote_part
            if "@" in rp.split(":", 1)[0]:
                user, resth = rp.split("@", 1)
            else:
                user, resth = "", rp
            host, rpath = resth.split(":", 1)
            rpath_gui = rpath.replace(r"\040", " ")

            new_entries.append({
                "mount_point": left,
                "user": user,
                "host": host,
                "remote_path": rpath_gui,
                "fstype": fstype,
                "identity_file": identity_file,
                "allow_other": allow_other,
                "uid": uid, "gid": gid, "umask": umask,
                "server_alive_interval": int(sai) if sai else 15,
                "server_alive_count": int(sac) if sac else 3,
                "reconnect": reconnect,
                "delay_connect": delay_connect,
                "extra_options": ",".join(extra_opts)
            })
        except Exception:
            continue
    return new_entries

