#!/usr/bin/env python3
# Autofs Manager GUI in Tkinter
# This script provides a GUI to manage common autofs use cases for SSHFS mounts.
# Features:
# - Create and edit direct map entries for SSHFS
# - Global map options: timeout, --ghost
# - Write /etc/auto.master.d/sshfs-manager.autofs and /etc/auto.sshfs-manager (if run as root)
# - Fallback: save to /tmp and show commands to install with sudo
# - Service controls: start/stop/restart/enable/disable/status for autofs
# - Fuse config toggle: enable user_allow_other in /etc/fuse.conf (or provide commands)
# - Test mount: ls on a mountpoint, quick status check
#
# Notes:
# - Run as root (sudo/python with pkexec) for writing system files & service actions.
# - Remote paths may contain spaces or non-ASCII; spaces will be escaped as \040 in map files.
# - This tool manages its own files:
#       /etc/auto.master.d/sshfs-manager.autofs
#       /etc/auto.sshfs-manager
#   It will not modify unrelated autofs configs.
#
# Save this file as autofs_manager.py and run:
#   sudo python3 autofs_manager.py
#
import os
import sys
import json
import shlex
import subprocess
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

APP_NAME = "Autofs Manager (SSHFS)"
APP_CONFIG_DIR = os.path.expanduser("~/.config/autofs_manager")
APP_CONFIG_FILE = os.path.join(APP_CONFIG_DIR, "state.json")

# System files managed by this app
MASTER_D_PATH = "/etc/auto.master.d/sshfs-manager.autofs"
MAP_FILE_PATH = "/etc/auto.sshfs-manager"
FUSE_CONF = "/etc/fuse.conf"

def is_root():
    try:
        return os.geteuid() == 0
    except AttributeError:
        # Windows / non-posix - not supported scenario for autofs
        return False

def run_cmd(cmd, timeout=15):
    try:
        proc = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
        return proc.returncode, proc.stdout.strip(), proc.stderr.strip()
    except subprocess.TimeoutExpired:
        return 124, "", f"Timeout executing: {cmd}"

def escape_spaces(path: str) -> str:
    # autofs maps require spaces escaped as \040
    return path.replace(" ", r"\040")

def ensure_config_dir():
    os.makedirs(APP_CONFIG_DIR, exist_ok=True)

def load_state():
    ensure_config_dir()
    if os.path.exists(APP_CONFIG_FILE):
        try:
            with open(APP_CONFIG_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def save_state(data):
    ensure_config_dir()
    with open(APP_CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

def read_file(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception as e:
        return None

def write_file_atomic(path, content):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(content)
    os.replace(tmp, path)

def build_master_file(timeout=120, ghost=True):
    # We manage a single direct map file MAP_FILE_PATH mounted at '/-'
    opts = [f"--timeout={int(timeout)}"]
    if ghost:
        opts.append("--ghost")
    body = f"/- {MAP_FILE_PATH} {' '.join(opts)}\n"
    header = (
        "# Managed by Autofs Manager GUI (SSHFS)\n"
        "# This file is auto-generated. Edit via the GUI or your changes may be overwritten.\n"
    )
    return header + body

def build_map_line(entry):
    # entry: dict with fields
    # Format: <mount_point> -fstype=fuse.sshfs,<options> :user@host:/remote/path
    mount_point = entry.get("mount_point", "").strip()
    user = entry.get("user", "").strip()
    host = entry.get("host", "").strip()
    remote_path = entry.get("remote_path", "").strip()
    fstype = entry.get("fstype", "fuse.sshfs").strip() or "fuse.sshfs"
    identity_file = entry.get("identity_file", "").strip()
    uid = entry.get("uid", "").strip()
    gid = entry.get("gid", "").strip()
    umask = entry.get("umask", "").strip()
    allow_other = entry.get("allow_other", False)
    reconnect = entry.get("reconnect", True)
    delay_connect = entry.get("delay_connect", True)
    sai = str(entry.get("server_alive_interval", "15")).strip()
    sac = str(entry.get("server_alive_count", "3")).strip()
    extra = entry.get("extra_options", "").strip()

    if not mount_point or not host or not remote_path:
        raise ValueError("Faltan campos: punto de montaje, host y/o ruta remota.")

    # Build options
    opts = [f"-fstype={fstype}"]
    if identity_file:
        opts.append(f"IdentityFile={identity_file}")
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
        # Allow comma-separated user-provided options
        for tok in extra.split(","):
            tok = tok.strip()
            if tok:
                opts.append(tok)

    # Escape spaces in remote path for autofs map (use \040 for spaces)
    remote_spec = f":{user + '@' if user else ''}{host}:{escape_spaces(remote_path)}"
    line = f"{mount_point} {','.join(opts)} {remote_spec}"
    return line

def build_map_file(entries):
    header = (
        "# Managed by Autofs Manager GUI (SSHFS)\n"
        "# Each line maps a local path to a remote SSHFS target with options.\n"
        "# Format:\n"
        "# /local/mount -fstype=fuse.sshfs,IdentityFile=/home/user/.ssh/id_ed25519,allow_other,uid=1000,gid=1000,umask=022,ServerAliveInterval=15,ServerAliveCountMax=3,reconnect,delay_connect :user@host:/remote/path\n\n"
    )
    lines = []
    for e in entries:
        lines.append(build_map_line(e))
    return header + "\n".join(lines) + ("\n" if lines else "")

class AutofsManagerGUI(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(APP_NAME)
        self.geometry("1100x750")
        self.minsize(980, 680)

        self.state_data = load_state()
        self.entries = self.state_data.get("entries", [])
        self.master_timeout = self.state_data.get("master_timeout", 120)
        self.master_ghost = self.state_data.get("master_ghost", True)

        self.create_widgets()

    def create_widgets(self):
        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill="both", expand=True)

        self.tab_maps = ttk.Frame(self.notebook)
        self.tab_service = ttk.Frame(self.notebook)
        self.tab_settings = ttk.Frame(self.notebook)
        self.tab_test = ttk.Frame(self.notebook)

        self.notebook.add(self.tab_maps, text="Mapas SSHFS")
        self.notebook.add(self.tab_service, text="Servicio Autofs")
        self.notebook.add(self.tab_settings, text="Ajustes")
        self.notebook.add(self.tab_test, text="Pruebas / Diagnóstico")

        self.build_maps_tab()
        self.build_service_tab()
        self.build_settings_tab()
        self.build_test_tab()

        self.status = tk.StringVar(value="Listo.")
        statusbar = ttk.Label(self, textvariable=self.status, anchor="w")
        statusbar.pack(fill="x", side="bottom")

    # ---------- Maps Tab ----------
    def build_maps_tab(self):
        top = ttk.Frame(self.tab_maps)
        top.pack(fill="both", expand=False, padx=10, pady=10)

        # Global master options
        master_frame = ttk.LabelFrame(top, text="Opciones globales del mapa (auto.master.d)")
        master_frame.pack(fill="x", pady=(0, 10))

        self.var_timeout = tk.IntVar(value=int(self.master_timeout))
        self.var_ghost = tk.BooleanVar(value=bool(self.master_ghost))

        ttk.Label(master_frame, text="Timeout (segundos):").grid(row=0, column=0, sticky="w", padx=5, pady=5)
        ttk.Entry(master_frame, textvariable=self.var_timeout, width=10).grid(row=0, column=1, sticky="w", padx=5, pady=5)
        ttk.Checkbutton(master_frame, text="--ghost (mostrar puntos aunque no estén montados)", variable=self.var_ghost).grid(row=0, column=2, sticky="w", padx=5, pady=5)

        # Entries list
        list_frame = ttk.LabelFrame(self.tab_maps, text="Entradas (direct map)")
        list_frame.pack(fill="both", expand=True, padx=10, pady=0)

        columns = ("mount_point", "user", "host", "remote_path", "identity_file", "allow_other", "uid", "gid", "umask", "options")
        self.tree = ttk.Treeview(list_frame, columns=columns, show="headings", height=8)
        for col, text in [
            ("mount_point", "Punto de montaje"),
            ("user", "Usuario"),
            ("host", "Host"),
            ("remote_path", "Ruta remota"),
            ("identity_file", "IdentityFile"),
            ("allow_other", "allow_other"),
            ("uid", "uid"),
            ("gid", "gid"),
            ("umask", "umask"),
            ("options", "Opc. extra"),
        ]:
            self.tree.heading(col, text=text)
            self.tree.column(col, width=140 if col in ("mount_point","remote_path") else 110, stretch=True)
        self.tree.pack(fill="both", expand=True, padx=5, pady=5)

        btns = ttk.Frame(list_frame)
        btns.pack(fill="x", pady=5)
        ttk.Button(btns, text="Añadir / Editar entrada", command=self.open_entry_editor).pack(side="left", padx=5)
        ttk.Button(btns, text="Eliminar seleccionada", command=self.delete_selected_entry).pack(side="left", padx=5)
        ttk.Button(btns, text="Guardar configuración", command=self.save_configuration).pack(side="right", padx=5)
        ttk.Button(btns, text="Cargar desde sistema", command=self.load_from_system_files).pack(side="right", padx=5)

        self.refresh_tree()

    def refresh_tree(self):
        for i in self.tree.get_children():
            self.tree.delete(i)
        for idx, e in enumerate(self.entries):
            self.tree.insert("", "end", iid=str(idx), values=(
                e.get("mount_point",""),
                e.get("user",""),
                e.get("host",""),
                e.get("remote_path",""),
                e.get("identity_file",""),
                "Sí" if e.get("allow_other") else "No",
                e.get("uid",""),
                e.get("gid",""),
                e.get("umask",""),
                e.get("extra_options",""),
            ))

    def open_entry_editor(self):
        selected = self.tree.selection()
        index = int(selected[0]) if selected else None
        EntryEditor(self, index)

    def delete_selected_entry(self):
        selected = self.tree.selection()
        if not selected:
            messagebox.showinfo(APP_NAME, "Selecciona una entrada para eliminar.")
            return
        idx = int(selected[0])
        if messagebox.askyesno(APP_NAME, "¿Eliminar la entrada seleccionada?"):
            del self.entries[idx]
            self.refresh_tree()
            self.set_status("Entrada eliminada. No olvides guardar configuración.")

    def save_configuration(self):
        # Update global opts
        self.master_timeout = int(self.var_timeout.get())
        self.master_ghost = bool(self.var_ghost.get())

        # Build contents
        try:
            master_body = build_master_file(self.master_timeout, self.master_ghost)
            map_body = build_map_file(self.entries)
        except Exception as e:
            messagebox.showerror(APP_NAME, f"Error construyendo archivos: {e}")
            return

        # Save state
        self.state_data["entries"] = self.entries
        self.state_data["master_timeout"] = self.master_timeout
        self.state_data["master_ghost"] = self.master_ghost
        save_state(self.state_data)

        # Try to write system files if root
        if is_root():
            try:
                write_file_atomic(MASTER_D_PATH, master_body)
                write_file_atomic(MAP_FILE_PATH, map_body)
                self.set_status(f"Archivos escritos en {MASTER_D_PATH} y {MAP_FILE_PATH}. Reinicia autofs para aplicar.")
                messagebox.showinfo(APP_NAME, f"Configuración guardada en sistema.\n\n{MASTER_D_PATH}\n{MAP_FILE_PATH}")
            except Exception as e:
                messagebox.showerror(APP_NAME, f"No se pudo escribir en /etc: {e}")
        else:
            # Fallback: write to /tmp and show instructions
            tmp_master = "/tmp/sshfs-manager.autofs"
            tmp_map = "/tmp/auto.sshfs-manager"
            try:
                write_file_atomic(tmp_master, master_body)
                write_file_atomic(tmp_map, map_body)
                instr = (
                    f"No tienes privilegios de root.\n\n"
                    f"Se guardaron archivos de ejemplo en:\n"
                    f"  {tmp_master}\n"
                    f"  {tmp_map}\n\n"
                    f"Para instalarlos:\n"
                    f"  sudo cp {tmp_master} {MASTER_D_PATH}\n"
                    f"  sudo cp {tmp_map} {MAP_FILE_PATH}\n"
                    f"  sudo systemctl restart autofs\n"
                )
                messagebox.showinfo(APP_NAME, instr)
                self.set_status("Configuración guardada en /tmp. Sigue las instrucciones para instalar.")
            except Exception as e:
                messagebox.showerror(APP_NAME, f"No se pudo guardar en /tmp: {e}")

    def load_from_system_files(self):
        # Only parse files we manage; ignore foreign files for safety.
        master_txt = read_file(MASTER_D_PATH)
        map_txt = read_file(MAP_FILE_PATH)
        if not master_txt and not map_txt:
            messagebox.showinfo(APP_NAME, "No se encontraron archivos gestionados por esta app en /etc.")
            return
        # Parse master timeout/ghost (best-effort)
        if master_txt:
            ghost = "--ghost" in master_txt
            to = 120
            for tok in master_txt.split():
                if tok.startswith("--timeout="):
                    try:
                        to = int(tok.split("=",1)[1])
                    except Exception:
                        pass
            self.var_timeout.set(to)
            self.var_ghost.set(ghost)
            self.master_timeout = to
            self.master_ghost = ghost

        # Parse map entries (best-effort for our managed format)
        new_entries = []
        if map_txt:
            for line in map_txt.splitlines():
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                # Expect: <mount> -fstype=fuse.sshfs,opt1,opt2 :user@host:/path
                try:
                    left, rest = line.split(" ", 1)
                    opts_part, remote_part = rest.rsplit(" ", 1)
                    # opts_part like: -fstype=fuse.sshfs,IdentityFile=...,allow_other,...
                    if not opts_part.startswith("-fstype="):
                        continue
                    # Extract fstype and options
                    opt_items = opts_part.split(",")
                    fstype = opt_items[0].split("=",1)[1]
                    opts = opt_items[1:]
                    identity_file = ""
                    allow_other = False
                    uid = gid = umask = ""
                    sai = sac = ""
                    reconnect = delay_connect = False
                    extra_opts = []

                    for o in opts:
                        if "=" in o:
                            k, v = o.split("=",1)
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

                    # remote_part like: :user@host:/remote/path
                    rp = remote_part[1:] if remote_part.startswith(":") else remote_part
                    if "@" in rp.split(":",1)[0]:
                        user, resth = rp.split("@",1)
                    else:
                        user, resth = "", rp
                    host, rpath = resth.split(":",1)

                    # Convert \040 back to spaces for GUI
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
                    # Ignore lines we don't fully understand (keep safe)
                    continue

        if new_entries:
            self.entries = new_entries
            self.refresh_tree()
            self.set_status("Configuración cargada desde /etc (archivos gestionados).")
        else:
            self.set_status("No se pudieron interpretar entradas del mapa.")

    # ---------- Service Tab ----------
    def build_service_tab(self):
        frm = ttk.Frame(self.tab_service)
        frm.pack(fill="both", expand=True, padx=10, pady=10)

        ttk.Label(frm, text="Control del servicio autofs (requiere root):").pack(anchor="w", pady=5)

        btns = ttk.Frame(frm)
        btns.pack(anchor="w", pady=5)

        ttk.Button(btns, text="status", command=lambda: self.service_action("status")).pack(side="left", padx=5)
        ttk.Button(btns, text="start", command=lambda: self.service_action("start")).pack(side="left", padx=5)
        ttk.Button(btns, text="stop", command=lambda: self.service_action("stop")).pack(side="left", padx=5)
        ttk.Button(btns, text="restart", command=lambda: self.service_action("restart")).pack(side="left", padx=5)
        ttk.Button(btns, text="enable", command=lambda: self.service_action("enable")).pack(side="left", padx=5)
        ttk.Button(btns, text="disable", command=lambda: self.service_action("disable")).pack(side="left", padx=5)

        self.txt_service = tk.Text(frm, height=20)
        self.txt_service.pack(fill="both", expand=True, pady=10)

    def service_action(self, action):
        if action == "status":
            cmd = "systemctl status autofs --no-pager"
        else:
            if not is_root():
                messagebox.showwarning(APP_NAME, f"La acción '{action}' requiere root.")
                return
            cmd = f"systemctl {action} autofs"
        rc, out, err = run_cmd(cmd, timeout=20)
        self.txt_service.delete("1.0", tk.END)
        self.txt_service.insert(tk.END, f"$ {cmd}\n\n")
        self.txt_service.insert(tk.END, out + ("\n" if out else ""))
        if err:
            self.txt_service.insert(tk.END, "\n[stderr]\n" + err + "\n")
        self.set_status(f"Ejecutado: {action} (rc={rc})")

    # ---------- Settings Tab ----------
    def build_settings_tab(self):
        frm = ttk.Frame(self.tab_settings)
        frm.pack(fill="both", expand=True, padx=10, pady=10)

        ttk.Label(frm, text="Ajustes útiles").pack(anchor="w", pady=5)

        # user_allow_other
        fuse_frame = ttk.LabelFrame(frm, text="FUSE (allow_other)")
        fuse_frame.pack(fill="x", pady=8)
        ttk.Label(fuse_frame, text="Habilitar 'user_allow_other' en /etc/fuse.conf").grid(row=0, column=0, sticky="w", padx=5, pady=5)
        ttk.Button(fuse_frame, text="Activar (root)", command=self.enable_user_allow_other).grid(row=0, column=1, padx=5, pady=5)
        ttk.Button(fuse_frame, text="Ver /etc/fuse.conf", command=self.view_fuse_conf).grid(row=0, column=2, padx=5, pady=5)

        # Packages check
        pkg_frame = ttk.LabelFrame(frm, text="Comprobaciones")
        pkg_frame.pack(fill="x", pady=8)
        ttk.Button(pkg_frame, text="Comprobar autofs/sshfs instalados", command=self.check_packages).grid(row=0, column=0, padx=5, pady=5)

        # Save/restore state
        state_frame = ttk.LabelFrame(frm, text="Estado de la app")
        state_frame.pack(fill="x", pady=8)
        ttk.Button(state_frame, text="Guardar estado (usuario)", command=lambda: save_state({"entries": self.entries, "master_timeout": self.var_timeout.get(), "master_ghost": self.var_ghost.get()})).grid(row=0, column=0, padx=5, pady=5)
        ttk.Button(state_frame, text="Cargar estado (usuario)", command=self.load_state_clicked).grid(row=0, column=1, padx=5, pady=5)

        # Info
        info = tk.Text(frm, height=10, wrap="word")
        info.pack(fill="both", expand=True, pady=8)
        info.insert(tk.END,
            "Este gestor escribe únicamente sus propios archivos:\n"
            f"  - {MASTER_D_PATH}\n"
            f"  - {MAP_FILE_PATH}\n\n"
            "Para usar opciones como 'allow_other', asegúrate de habilitar 'user_allow_other' en /etc/fuse.conf.\n"
            "Ejecuta esta app como root para aplicar cambios en el sistema y controlar el servicio autofs.\n"
        )
        info.configure(state="disabled")

    def load_state_clicked(self):
        self.state_data = load_state()
        self.entries = self.state_data.get("entries", [])
        self.var_timeout.set(int(self.state_data.get("master_timeout", 120)))
        self.var_ghost.set(bool(self.state_data.get("master_ghost", True)))
        self.refresh_tree()
        self.set_status("Estado de usuario cargado.")

    def enable_user_allow_other(self):
        if not is_root():
            messagebox.showwarning(APP_NAME, "Requiere root.")
            return
        txt = read_file(FUSE_CONF) or ""
        if "user_allow_other" in txt and not txt.strip().startswith("#"):
            messagebox.showinfo(APP_NAME, "Parece que 'user_allow_other' ya está habilitado.")
            return
        try:
            if txt and "user_allow_other" in txt:
                new = txt.replace("#user_allow_other", "user_allow_other")
            else:
                new = (txt + "\n" if txt else "") + "user_allow_other\n"
            write_file_atomic(FUSE_CONF, new)
            self.set_status("user_allow_other habilitado en /etc/fuse.conf")
            messagebox.showinfo(APP_NAME, "Se habilitó 'user_allow_other' en /etc/fuse.conf")
        except Exception as e:
            messagebox.showerror(APP_NAME, f"No se pudo modificar /etc/fuse.conf: {e}")

    def view_fuse_conf(self):
        txt = read_file(FUSE_CONF)
        if txt is None:
            messagebox.showinfo(APP_NAME, "No se pudo leer /etc/fuse.conf (o no existe).")
            return
        viewer = tk.Toplevel(self)
        viewer.title("/etc/fuse.conf")
        t = tk.Text(viewer, wrap="word")
        t.pack(fill="both", expand=True)
        t.insert(tk.END, txt)
        t.configure(state="disabled")

    def check_packages(self):
        rc1, out1, _ = run_cmd("command -v automount || command -v autofs")
        rc2, out2, _ = run_cmd("command -v sshfs")
        msg = []
        msg.append(f"autofs: {'OK ('+ (out1 or 'found') +')' if rc1 == 0 else 'NO ENCONTRADO'}")
        msg.append(f"sshfs: {'OK ('+ (out2 or 'found') +')' if rc2 == 0 else 'NO ENCONTRADO'}")
        messagebox.showinfo(APP_NAME, "\n".join(msg))

    # ---------- Test Tab ----------
    def build_test_tab(self):
        frm = ttk.Frame(self.tab_test)
        frm.pack(fill="both", expand=True, padx=10, pady=10)

        ttk.Label(frm, text="Pruebas rápidas (usa tus puntos de montaje)").pack(anchor="w")

        top = ttk.Frame(frm)
        top.pack(fill="x", pady=5)
        ttk.Label(top, text="Ruta local (punto de montaje):").pack(side="left", padx=5)
        self.var_test_path = tk.StringVar()
        ttk.Entry(top, textvariable=self.var_test_path, width=60).pack(side="left", padx=5)
        ttk.Button(top, text="LS", command=self.test_ls).pack(side="left", padx=5)
        ttk.Button(top, text="Abrir carpeta…", command=self.browse_mount_point).pack(side="left", padx=5)
        ttk.Button(top, text="umount (forzar)", command=self.force_umount).pack(side="right", padx=5)

        self.txt_test = tk.Text(frm, height=22)
        self.txt_test.pack(fill="both", expand=True, pady=8)

    def browse_mount_point(self):
        path = filedialog.askdirectory(title="Selecciona el punto de montaje")
        if path:
            self.var_test_path.set(path)

    def test_ls(self):
        path = self.var_test_path.get().strip()
        if not path:
            messagebox.showinfo(APP_NAME, "Indica una ruta local.")
            return
        cmd = f"ls -la {shlex.quote(path)}"
        rc, out, err = run_cmd(cmd, timeout=20)
        self.txt_test.delete("1.0", tk.END)
        self.txt_test.insert(tk.END, f"$ {cmd}\n\n")
        self.txt_test.insert(tk.END, out + ("\n" if out else ""))
        if err:
            self.txt_test.insert(tk.END, "\n[stderr]\n" + err + "\n")
        self.set_status(f"LS rc={rc}. Si no estaba montado, autofs habrá intentado montarlo al acceder.")

    def force_umount(self):
        if not is_root():
            messagebox.showwarning(APP_NAME, "umount requiere root.")
            return
        path = self.var_test_path.get().strip()
        if not path:
            messagebox.showinfo(APP_NAME, "Indica una ruta local.")
            return
        cmd = f"umount -f {shlex.quote(path)}"
        rc, out, err = run_cmd(cmd, timeout=20)
        self.txt_test.delete("1.0", tk.END)
        self.txt_test.insert(tk.END, f"$ {cmd}\n\n")
        self.txt_test.insert(tk.END, out + ("\n" if out else ""))
        if err:
            self.txt_test.insert(tk.END, "\n[stderr]\n" + err + "\n")
        self.set_status(f"umount rc={rc}")

    # ---------- Helpers ----------
    def set_status(self, txt):
        self.status.set(txt)

class EntryEditor(tk.Toplevel):
    def __init__(self, app: AutofsManagerGUI, index=None):
        super().__init__(app)
        self.app = app
        self.index = index
        self.title("Añadir / Editar entrada SSHFS")
        self.geometry("820x520")
        self.resizable(True, True)

        e = app.entries[index] if index is not None else {}
        # Variables
        self.var_mount = tk.StringVar(value=e.get("mount_point",""))
        self.var_user = tk.StringVar(value=e.get("user",""))
        self.var_host = tk.StringVar(value=e.get("host",""))
        self.var_rpath = tk.StringVar(value=e.get("remote_path",""))
        self.var_fstype = tk.StringVar(value=e.get("fstype","fuse.sshfs"))
        self.var_identity = tk.StringVar(value=e.get("identity_file",""))
        self.var_allow_other = tk.BooleanVar(value=e.get("allow_other", True))
        self.var_uid = tk.StringVar(value=e.get("uid","1000"))
        self.var_gid = tk.StringVar(value=e.get("gid","1000"))
        self.var_umask = tk.StringVar(value=e.get("umask","022"))
        self.var_sai = tk.IntVar(value=int(e.get("server_alive_interval", 15)))
        self.var_sac = tk.IntVar(value=int(e.get("server_alive_count", 3)))
        self.var_reconnect = tk.BooleanVar(value=e.get("reconnect", True))
        self.var_delay = tk.BooleanVar(value=e.get("delay_connect", True))
        self.var_extra = tk.StringVar(value=e.get("extra_options",""))

        frm = ttk.Frame(self)
        frm.pack(fill="both", expand=True, padx=10, pady=10)

        # Left column
        left = ttk.Frame(frm)
        left.pack(side="left", fill="both", expand=True, padx=(0,8))

        ttk.Label(left, text="Punto de montaje (local):").grid(row=0, column=0, sticky="w", pady=4)
        row0 = ttk.Frame(left); row0.grid(row=0, column=1, sticky="we", pady=4)
        ttk.Entry(row0, textvariable=self.var_mount, width=40).pack(side="left", fill="x", expand=True)
        ttk.Button(row0, text="Elegir…", command=self.choose_mount_dir).pack(side="left", padx=4)

        ttk.Label(left, text="Usuario remoto:").grid(row=1, column=0, sticky="w", pady=4)
        ttk.Entry(left, textvariable=self.var_user, width=30).grid(row=1, column=1, sticky="w", pady=4)

        ttk.Label(left, text="Host remoto:").grid(row=2, column=0, sticky="w", pady=4)
        ttk.Entry(left, textvariable=self.var_host, width=30).grid(row=2, column=1, sticky="w", pady=4)

        ttk.Label(left, text="Ruta remota:").grid(row=3, column=0, sticky="w", pady=4)
        row3 = ttk.Frame(left); row3.grid(row=3, column=1, sticky="we", pady=4)
        ttk.Entry(row3, textvariable=self.var_rpath, width=40).pack(side="left", fill="x", expand=True)
        ttk.Button(row3, text="…", command=self.hint_remote_path).pack(side="left", padx=4)

        ttk.Label(left, text="IdentityFile (clave SSH):").grid(row=4, column=0, sticky="w", pady=4)
        row4 = ttk.Frame(left); row4.grid(row=4, column=1, sticky="we", pady=4)
        ttk.Entry(row4, textvariable=self.var_identity, width=40).pack(side="left", fill="x", expand=True)
        ttk.Button(row4, text="Elegir…", command=self.choose_identity_file).pack(side="left", padx=4)

        ttk.Label(left, text="fstype:").grid(row=5, column=0, sticky="w", pady=4)
        ttk.Combobox(left, textvariable=self.var_fstype, values=["fuse.sshfs"], state="readonly", width=28).grid(row=5, column=1, sticky="w", pady=4)

        ttk.Label(left, text="Opciones extra (coma-separadas):").grid(row=6, column=0, sticky="w", pady=4)
        ttk.Entry(left, textvariable=self.var_extra, width=45).grid(row=6, column=1, sticky="we", pady=4)

        # Right column
        right = ttk.LabelFrame(frm, text="Permisos y fiabilidad")
        right.pack(side="left", fill="both", expand=True)

        ttk.Checkbutton(right, text="allow_other", variable=self.var_allow_other).grid(row=0, column=0, sticky="w", padx=5, pady=4)
        ttk.Label(right, text="uid:").grid(row=1, column=0, sticky="w", padx=5, pady=4)
        ttk.Entry(right, textvariable=self.var_uid, width=8).grid(row=1, column=1, sticky="w", padx=5, pady=4)
        ttk.Label(right, text="gid:").grid(row=1, column=2, sticky="w", padx=5, pady=4)
        ttk.Entry(right, textvariable=self.var_gid, width=8).grid(row=1, column=3, sticky="w", padx=5, pady=4)
        ttk.Label(right, text="umask:").grid(row=1, column=4, sticky="w", padx=5, pady=4)
        ttk.Entry(right, textvariable=self.var_umask, width=8).grid(row=1, column=5, sticky="w", padx=5, pady=4)

        ttk.Label(right, text="ServerAliveInterval:").grid(row=2, column=0, sticky="w", padx=5, pady=4)
        ttk.Entry(right, textvariable=self.var_sai, width=8).grid(row=2, column=1, sticky="w", padx=5, pady=4)
        ttk.Label(right, text="ServerAliveCountMax:").grid(row=2, column=2, sticky="w", padx=5, pady=4)
        ttk.Entry(right, textvariable=self.var_sac, width=8).grid(row=2, column=3, sticky="w", padx=5, pady=4)

        ttk.Checkbutton(right, text="reconnect", variable=self.var_reconnect).grid(row=3, column=0, sticky="w", padx=5, pady=4)
        ttk.Checkbutton(right, text="delay_connect", variable=self.var_delay).grid(row=3, column=1, sticky="w", padx=5, pady=4)

        # Buttons
        btns = ttk.Frame(self)
        btns.pack(fill="x", side="bottom", padx=10, pady=8)
        ttk.Button(btns, text="Guardar", command=self.save_entry).pack(side="right", padx=6)
        ttk.Button(btns, text="Cancelar", command=self.destroy).pack(side="right", padx=6)

    def choose_mount_dir(self):
        path = filedialog.askdirectory(title="Selecciona el punto de montaje (directorio local)")
        if path:
            self.var_mount.set(path)

    def choose_identity_file(self):
        path = filedialog.askopenfilename(title="Selecciona la clave privada SSH", initialdir=os.path.expanduser("~/.ssh"))
        if path:
            self.var_identity.set(path)

    def hint_remote_path(self):
        messagebox.showinfo(APP_NAME, "Introduce la ruta remota tal cual existe en el servidor (p. ej. /home/andres/Música). Las espacios se manejarán automáticamente.")

    def save_entry(self):
        # Validate and save to app entries
        e = {
            "mount_point": self.var_mount.get().strip(),
            "user": self.var_user.get().strip(),
            "host": self.var_host.get().strip(),
            "remote_path": self.var_rpath.get().strip(),
            "fstype": self.var_fstype.get().strip() or "fuse.sshfs",
            "identity_file": self.var_identity.get().strip(),
            "allow_other": bool(self.var_allow_other.get()),
            "uid": self.var_uid.get().strip(),
            "gid": self.var_gid.get().strip(),
            "umask": self.var_umask.get().strip(),
            "server_alive_interval": int(self.var_sai.get() or 15),
            "server_alive_count": int(self.var_sac.get() or 3),
            "reconnect": bool(self.var_reconnect.get()),
            "delay_connect": bool(self.var_delay.get()),
            "extra_options": self.var_extra.get().strip(),
        }
        if not e["mount_point"]:
            messagebox.showerror(APP_NAME, "El punto de montaje es obligatorio.")
            return
        if not e["host"] or not e["remote_path"]:
            messagebox.showerror(APP_NAME, "Host y ruta remota son obligatorios.")
            return
        # Ensure mount directory exists (best-effort)
        try:
            os.makedirs(e["mount_point"], exist_ok=True)
        except Exception:
            pass

        try:
            # Build once to validate
            _ = build_map_line(e)
        except Exception as ex:
            messagebox.showerror(APP_NAME, f"Entrada inválida: {ex}")
            return

        if self.index is None:
            self.app.entries.append(e)
        else:
            self.app.entries[self.index] = e
        self.app.refresh_tree()
        self.app.set_status("Entrada guardada en la app (pendiente de 'Guardar configuración').")
        self.destroy()

if __name__ == "__main__":
    app = AutofsManagerGUI()
    app.mainloop()
