from __future__ import annotations

import json
import os
from datetime import datetime
import threading
from typing import List, Optional, Tuple
from shlex import quote as shlex_quote

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QGroupBox,
    QTableWidget,
    QTableWidgetItem,
    QPushButton,
    QMessageBox,
    QPlainTextEdit,
    QLabel,
    QSpinBox,
    QCheckBox,
    QAbstractItemView,
    QInputDialog,
    QLineEdit,
    QDialog,
    QFormLayout,
    QDialogButtonBox,
    QFileDialog,
    QApplication,
    QComboBox,
)

from autofs_gui.application.factory import make_usecases
from autofs_gui.domain.models import AppState, SshfsEntry
from autofs_gui.domain.validation import validate_entry
from autofs_gui.infrastructure.repositories import load_state, save_state, APP_CONFIG_FILE
from autofs_gui.infrastructure.system import is_root
from autofs_gui.infrastructure.discovery import discover_hosts, HostCandidate


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("AutoFS GUI")

        self.usecases = make_usecases(ask_pass=self._prompt_sudo_password)
        self.app_state, initial_message = self._load_initial_state()
        self._dirty = False
        self._last_status_state: Optional[str] = None
        self._apply_timer: Optional[QTimer] = None
        self._pending_apply_reason: Optional[str] = None
        self._is_applying = False

        self._build_ui()
        self._restore_ui_state()
        self._apply_master_options()
        self._refresh_entries_table()
        self._mark_dirty(False)
        if initial_message:
            self._append_output(initial_message)
        self._warm_host_cache()
        self._start_status_monitor()
        self._load_from_system(initial=True)

    # ------------------------------------------------------------------ UI setup
    def _build_ui(self) -> None:
        central = QWidget(self)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(12, 12, 12, 12)
        main_layout.setSpacing(10)

        content_layout = QHBoxLayout()
        content_layout.setSpacing(12)
        main_layout.addLayout(content_layout, stretch=1)

        left_col = QVBoxLayout()
        left_col.setSpacing(10)
        content_layout.addLayout(left_col, stretch=1)

        master_box = QGroupBox("Opciones master", central)
        master_layout = QHBoxLayout(master_box)
        master_layout.setContentsMargins(10, 8, 10, 8)
        master_layout.addWidget(QLabel("Timeout (s):", master_box))
        self.timeout_spin = QSpinBox(master_box)
        self.timeout_spin.setRange(0, 86400)
        self.timeout_spin.setSingleStep(5)
        self.timeout_spin.valueChanged.connect(self._on_timeout_changed)
        master_layout.addWidget(self.timeout_spin)

        self.ghost_checkbox = QCheckBox("--ghost", master_box)
        self.ghost_checkbox.toggled.connect(self._on_ghost_toggled)
        master_layout.addWidget(self.ghost_checkbox)
        master_layout.addStretch()
        left_col.addWidget(master_box)

        status_box = QGroupBox("Estado del servicio autofs", central)
        status_layout = QHBoxLayout(status_box)
        status_layout.setContentsMargins(10, 8, 10, 8)
        status_layout.setSpacing(10)

        self.status_indicator = QLabel(status_box)
        self.status_indicator.setFixedSize(16, 16)
        self.status_indicator.setStyleSheet(self._indicator_style("#cccccc"))
        status_layout.addWidget(self.status_indicator)

        self.status_label = QLabel("Verificando estado...", status_box)
        status_layout.addWidget(self.status_label, stretch=1)

        self.btn_service_start = QPushButton("Iniciar", status_box)
        self.btn_service_start.setToolTip("Inicia el servicio autofs para habilitar los montajes automáticos.")
        self.btn_service_start.clicked.connect(lambda: self._service_action("start"))
        status_layout.addWidget(self.btn_service_start)

        self.btn_service_stop = QPushButton("Detener", status_box)
        self.btn_service_stop.setToolTip("Detiene el servicio autofs; los montajes automáticos dejarán de ejecutarse.")
        self.btn_service_stop.clicked.connect(lambda: self._service_action("stop"))
        status_layout.addWidget(self.btn_service_stop)

        self.btn_service_restart = QPushButton("Reiniciar", status_box)
        self.btn_service_restart.setToolTip("Reinicia el servicio autofs para aplicar cambios recientes.")
        self.btn_service_restart.clicked.connect(lambda: self._service_action("restart"))
        status_layout.addWidget(self.btn_service_restart)

        status_layout.addStretch()
        left_col.addWidget(status_box)

        self.entries_table = QTableWidget(0, 4, central)
        self.entries_table.setHorizontalHeaderLabels(["Montaje", "Host", "Ruta remota", "Usuario"])
        self.entries_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.entries_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.entries_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.entries_table.horizontalHeader().setStretchLastSection(True)
        self.entries_table.verticalHeader().setVisible(False)
        self.entries_table.itemSelectionChanged.connect(self._update_entry_detail)
        left_col.addWidget(self.entries_table, stretch=1)

        btn_row = QHBoxLayout()
        self.btn_add = QPushButton("Agregar")
        self.btn_add.clicked.connect(self._add_entry)
        self.btn_add.setToolTip("Crear una nueva entrada SSHFS para autofs.")
        btn_row.addWidget(self.btn_add)

        self.btn_edit = QPushButton("Editar")
        self.btn_edit.clicked.connect(self._edit_entry)
        self.btn_edit.setToolTip("Modificar la entrada seleccionada.")
        btn_row.addWidget(self.btn_edit)

        self.btn_delete = QPushButton("Eliminar")
        self.btn_delete.clicked.connect(self._delete_entry)
        self.btn_delete.setToolTip("Eliminar la entrada seleccionada de la lista.")
        btn_row.addWidget(self.btn_delete)

        btn_row.addStretch()
        left_col.addLayout(btn_row)

        entry_action_row = QHBoxLayout()
        self.btn_test_ssh = QPushButton("Probar conexión SSH")
        self.btn_test_ssh.clicked.connect(self._test_selected_entry)
        self.btn_test_ssh.setToolTip("Verifica la conectividad SSH y la ruta remota para la entrada seleccionada.")
        entry_action_row.addWidget(self.btn_test_ssh)

        self.btn_ls = QPushButton("Listar montaje")
        self.btn_ls.clicked.connect(self._list_selected_entry)
        self.btn_ls.setToolTip("Lista el contenido del punto de montaje configurado.")
        entry_action_row.addWidget(self.btn_ls)

        self.btn_umount = QPushButton("Desmontar")
        self.btn_umount.clicked.connect(self._umount_selected_entry)
        self.btn_umount.setToolTip("Fuerza el desmontaje del punto de montaje local.")
        entry_action_row.addWidget(self.btn_umount)

        entry_action_row.addStretch()
        left_col.addLayout(entry_action_row)

        detail_box = QGroupBox("Detalle de la entrada seleccionada", central)
        detail_layout = QVBoxLayout(detail_box)
        detail_actions = QHBoxLayout()
        detail_actions.addStretch()
        self.btn_copy_detail = QPushButton("Copiar detalle")
        self.btn_copy_detail.setToolTip("Copia el detalle de la entrada en formato JSON al portapapeles.")
        self.btn_copy_detail.clicked.connect(self._copy_entry_detail)
        detail_actions.addWidget(self.btn_copy_detail)
        detail_layout.addLayout(detail_actions)
        self.entry_detail_table = QTableWidget(detail_box)
        self.entry_detail_table.setColumnCount(2)
        self.entry_detail_table.setHorizontalHeaderLabels(["Campo", "Valor"])
        self.entry_detail_table.horizontalHeader().setStretchLastSection(True)
        self.entry_detail_table.verticalHeader().setVisible(False)
        self.entry_detail_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.entry_detail_table.setSelectionMode(QAbstractItemView.SingleSelection)
        detail_layout.addWidget(self.entry_detail_table)
        left_col.addWidget(detail_box)

        logs_box = QGroupBox("Registros", central)
        logs_box.setVisible(False)
        logs_layout = QVBoxLayout(logs_box)
        logs_layout.setContentsMargins(10, 8, 10, 8)
        logs_layout.setSpacing(4)
        logs_actions = QHBoxLayout()
        logs_actions.addStretch()
        self.btn_copy_logs = QPushButton("Copiar registros")
        self.btn_copy_logs.setToolTip("Copia el contenido actual de los registros al portapapeles.")
        self.btn_copy_logs.clicked.connect(self._copy_logs)
        logs_actions.addWidget(self.btn_copy_logs)
        logs_layout.addLayout(logs_actions)
        self.output_text = QPlainTextEdit(logs_box)
        self.output_text.setReadOnly(True)
        self.output_text.setMinimumHeight(200)
        self.output_text.setPlaceholderText("Aquí se mostrarán las operaciones ejecutadas y resultados.")
        logs_layout.addWidget(self.output_text)
        main_layout.addWidget(logs_box)

        self.logs_box = logs_box
        toggle_row = QHBoxLayout()
        self.btn_toggle_logs = QPushButton("Mostrar registros")
        self.btn_toggle_logs.setCheckable(True)
        self.btn_toggle_logs.setChecked(False)
        self.btn_toggle_logs.toggled.connect(self._toggle_logs)
        self.btn_toggle_logs.setToolTip("Mostrar u ocultar el panel de registros.")
        toggle_row.addWidget(self.btn_toggle_logs)
        toggle_row.addStretch()
        main_layout.addLayout(toggle_row)

        self.setCentralWidget(central)
        self.statusBar().showMessage("Listo.")
        self.dirty_label = QLabel("Sin cambios", self)
        self.statusBar().addPermanentWidget(self.dirty_label)

    # ---------------------------------------------------------------- state helpers
    def _load_initial_state(self) -> Tuple[AppState, str]:
        data = load_state()
        if data:
            try:
                return AppState.from_dict(data), f"Estado cargado desde {APP_CONFIG_FILE}"
            except Exception as exc:
                return AppState(), f"No se pudo cargar el estado guardado ({exc})."
        return AppState(), "Sin estado previo. Puedes cargar desde /etc o agregar entradas nuevas."

    def _warm_host_cache(self) -> None:
        def worker():
            try:
                discover_hosts(force=True)
                QTimer.singleShot(0, lambda: None)  # trigger UI loop
            except Exception as exc:
                QTimer.singleShot(0, lambda e=exc: self._append_output(
                    f"No se pudo precargar el listado de hosts: {e}", level="warning"
                ))
        threading.Thread(target=worker, daemon=True).start()

    def _apply_master_options(self) -> None:
        self.timeout_spin.blockSignals(True)
        self.ghost_checkbox.blockSignals(True)
        self.timeout_spin.setValue(self.app_state.master_options.timeout)
        self.ghost_checkbox.setChecked(self.app_state.master_options.ghost)
        self.timeout_spin.blockSignals(False)
        self.ghost_checkbox.blockSignals(False)

    def _restore_ui_state(self) -> None:
        geo = self.app_state.ui.window_geometry
        if geo:
            try:
                self.restoreGeometry(bytes.fromhex(geo))
            except Exception:
                pass

    def _remember_ui_state(self) -> None:
        self.app_state.ui.window_geometry = self.saveGeometry().toHex().data().decode("ascii")

    def _refresh_entries_table(self) -> None:
        entries = self.app_state.entries
        self.entries_table.setRowCount(len(entries))
        for row, entry in enumerate(entries):
            values = [
                entry.mount_point,
                entry.host,
                entry.remote_path,
                entry.user or "-",
            ]
            for col, value in enumerate(values):
                item = QTableWidgetItem(value)
                self.entries_table.setItem(row, col, item)
        if entries:
            self.entries_table.selectRow(0)
        else:
            self.entry_detail.clear()

    def _current_entry_index(self) -> Optional[int]:
        selected = self.entries_table.selectionModel().selectedRows() if self.entries_table.selectionModel() else []
        if not selected:
            return None
        return selected[0].row()

    def _current_entry_json(self) -> Optional[dict]:
        idx = self._current_entry_index()
        if idx is None or idx >= len(self.app_state.entries):
            return None
        return self.app_state.entries[idx].to_dict()

    def _entries_dicts(self) -> List[dict]:
        prepared = []
        for entry in self.app_state.entries:
            data = entry.to_dict()
            try:
                new_identity = self.usecases.ensure_root_access(data)
                if new_identity:
                    data["identity_file"] = new_identity
            except Exception as exc:
                self._append_output(
                    f"No se pudo preparar el acceso SSH para {data.get('host')}: {exc}",
                    level="warning",
                )
            prepared.append(data)
        return prepared

    # ---------------------------------------------------------------- event handlers
    def _indicator_style(self, color: str) -> str:
        return (
            "border: 1px solid #555;"
            "border-radius: 8px;"
            f"background-color: {color};"
        )

    def _set_service_state(self, state: str, description: str) -> None:
        color_map = {
            "running": "#5cb85c",
            "stopped": "#d9534f",
            "checking": "#f0ad4e",
            "unknown": "#f0ad4e",
        }
        color = color_map.get(state, "#cccccc")
        self.status_indicator.setStyleSheet(self._indicator_style(color))
        self.status_label.setText(description)

        previous = getattr(self, "_last_status_state", None)
        if state != previous and previous is not None:
            messages = {
                "running": ("El servicio autofs está activo.", "success"),
                "stopped": ("El servicio autofs está detenido.", "warning"),
                "checking": ("Verificando el estado del servicio...", "info"),
                "unknown": ("No fue posible determinar el estado del servicio autofs.", "warning"),
            }
            msg, level = messages.get(state, (None, "info"))
            if msg:
                self._append_output(msg, level=level)
        self._last_status_state = state

    def _set_service_buttons_enabled(self, enabled: bool) -> None:
        for btn in (self.btn_service_start, self.btn_service_stop, self.btn_service_restart):
            btn.setEnabled(enabled)

    def _short_text(self, text: str, limit: int = 400) -> str:
        snippet = (text or "").strip()
        if len(snippet) <= limit:
            return snippet
        return snippet[: limit - 3] + "..."

    def _start_status_monitor(self) -> None:
        self._set_service_state("checking", "Verificando estado del servicio...")
        self.status_timer = QTimer(self)
        self.status_timer.setInterval(5000)
        self.status_timer.timeout.connect(self._check_service_status)
        self._check_service_status()
        self.status_timer.start()

    def _check_service_status(self) -> None:
        try:
            rc, out, err = self.usecases.service("status")
        except Exception as exc:
            self._set_service_state("unknown", f"No se pudo consultar el estado: {exc}")
            return

        text = (out or err or "").lower()
        if rc == 0 and "active:" in text and "running" in text:
            self._set_service_state("running", "Servicio en ejecución.")
        elif "activating" in text or "starting" in text:
            self._set_service_state("checking", "Servicio iniciando...")
        elif "inactive" in text or "failed" in text or rc != 0:
            detail = "Servicio detenido." if "failed" not in text else "Servicio con errores."
            self._set_service_state("stopped", detail)
        else:
            self._set_service_state("unknown", "Estado desconocido. Revisa los registros.")

    def _on_timeout_changed(self, value: int) -> None:
        self.app_state.master_options.timeout = int(value)
        self._mark_dirty(True, "Timeout actualizado.")

    def _on_ghost_toggled(self, checked: bool) -> None:
        self.app_state.master_options.ghost = bool(checked)
        self._mark_dirty(True, "Opción --ghost actualizada.")

    def _update_entry_detail(self) -> None:
        idx = self._current_entry_index()
        data = self._current_entry_json() if idx is not None else None
        self.entry_detail_table.setRowCount(0)
        if not data:
            return

        translations = {
            "mount_point": "Punto de montaje",
            "host": "Host",
            "remote_path": "Ruta remota",
            "user": "Usuario",
            "fstype": "Tipo de sistema de archivos",
            "identity_file": "Archivo de identidad",
            "allow_other": "Permitir otros usuarios",
            "uid": "UID",
            "gid": "GID",
            "umask": "Umask",
            "server_alive_interval": "Intervalo keepalive",
            "server_alive_count": "Reintentos keepalive",
            "reconnect": "Reconectar",
            "delay_connect": "Conexión diferida",
            "extra_options": "Opciones adicionales",
        }

        rows = []
        for key, value in data.items():
            label = translations.get(key, key)
            if isinstance(value, bool):
                value_str = "Sí" if value else "No"
            else:
                value_str = str(value)
            rows.append((label, value_str))

        self.entry_detail_table.setRowCount(len(rows))
        for row, (label, value) in enumerate(rows):
            self.entry_detail_table.setItem(row, 0, QTableWidgetItem(label))
            self.entry_detail_table.setItem(row, 1, QTableWidgetItem(value))

    def _prompt_sudo_password(self) -> Optional[str]:
        pwd, ok = QInputDialog.getText(
            self,
            "Contraseña sudo",
            "Se requiere la contraseña de sudo:",
            QLineEdit.EchoMode.Password,
        )
        return pwd if ok and pwd else None

    def _selected_entry_or_warn(self, action_title: str) -> Optional[SshfsEntry]:
        idx = self._current_entry_index()
        if idx is None:
            QMessageBox.information(self, action_title, "Selecciona una entrada primero.")
            return None
        return self.app_state.entries[idx]

    # ---------------------------------------------------------------- actions
    def _add_entry(self) -> None:
        dialog = EntryDialog(self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            entry = dialog.get_entry()
            if entry:
                self.app_state.entries.append(entry)
                self._refresh_entries_table()
                self._mark_dirty(True, "Se agregó una entrada.")

    def _edit_entry(self) -> None:
        idx = self._current_entry_index()
        if idx is None:
            QMessageBox.information(self, "Editar entrada", "Selecciona una entrada primero.")
            return
        dialog = EntryDialog(self, self.app_state.entries[idx])
        if dialog.exec() == QDialog.DialogCode.Accepted:
            entry = dialog.get_entry()
            if entry:
                self.app_state.entries[idx] = entry
                self._refresh_entries_table()
                self.entries_table.selectRow(idx)
                self._mark_dirty(True, "Se actualizó una entrada.")

    def _delete_entry(self) -> None:
        idx = self._current_entry_index()
        if idx is None:
            QMessageBox.information(self, "Eliminar entrada", "Selecciona una entrada primero.")
            return
        entry = self.app_state.entries[idx]
        confirm = QMessageBox.question(
            self,
            "Eliminar entrada",
            f"¿Eliminar la entrada para '{entry.mount_point}'?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if confirm == QMessageBox.StandardButton.Yes:
            del self.app_state.entries[idx]
            self._refresh_entries_table()
            self._mark_dirty(True, "Se eliminó una entrada.")

    def _test_selected_entry(self) -> None:
        entry = self._selected_entry_or_warn("Probar conexión SSH")
        if not entry:
            return
        try:
            rc, out, err = self.usecases.ssh_test(entry.to_dict(), check_path=True, timeout_sec=10)
        except Exception as exc:
            self._show_error(f"No se pudo ejecutar la prueba SSH: {exc}")
            return
        if rc == 0:
            message = f"La conexión SSH hacia {entry.host} respondió correctamente."
            self._append_output(message, level="success")
            QMessageBox.information(self, "Prueba SSH", message)
        else:
            detail = self._short_text(err or out or "Sin detalles disponibles.")
            message = f"La prueba SSH para {entry.host} no fue exitosa (código {rc})."
            self._append_output(f"{message} Detalle: {detail}", level="warning")
            QMessageBox.warning(self, "Prueba SSH", f"{message}\n\nDetalle:\n{detail}")

    def _list_selected_entry(self) -> None:
        entry = self._selected_entry_or_warn("Listar montaje")
        if not entry:
            return
        try:
            rc, out, err = self.usecases.test_ls(entry.mount_point)
        except Exception as exc:
            self._show_error(f"No se pudo ejecutar ls en '{entry.mount_point}': {exc}")
            return
        if rc == 0:
            listing = self._short_text(out or "No se encontró contenido.", limit=600)
            message = f"Contenido de {entry.mount_point}:\n{listing}"
            self._append_output(message, level="info")
            QMessageBox.information(self, "Contenido del montaje", message)
        else:
            detail = self._short_text(err or out or "Sin detalles disponibles.")
            message = f"No se pudo listar el punto de montaje {entry.mount_point} (código {rc})."
            self._append_output(f"{message} Detalle: {detail}", level="warning")
            QMessageBox.warning(self, "Contenido del montaje", f"{message}\n\nDetalle:\n{detail}")

    def _umount_selected_entry(self) -> None:
        entry = self._selected_entry_or_warn("Desmontar")
        if not entry:
            return
        confirm = QMessageBox.question(
            self,
            "Desmontar",
            f"¿Desmontar el punto '{entry.mount_point}'?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return
        try:
            rc, out, err = self.usecases.umount(entry.mount_point)
        except Exception as exc:
            self._show_error(f"No se pudo desmontar '{entry.mount_point}': {exc}")
            return
        if rc == 0:
            message = f"El punto de montaje {entry.mount_point} se desmontó correctamente."
            self._append_output(message, level="success")
            QMessageBox.information(self, "Desmontar", message)
        else:
            detail = self._short_text(err or out or "Sin detalles disponibles.")
            message = f"No se pudo desmontar {entry.mount_point} (código {rc})."
            self._append_output(f"{message} Detalle: {detail}", level="warning")
            QMessageBox.warning(self, "Desmontar", f"{message}\n\nDetalle:\n{detail}")

    def _load_from_system(self, initial: bool = False) -> None:
        try:
            entries, timeout, ghost = self.usecases.load_from_system()
        except Exception as exc:
            self._show_error(f"No se pudo cargar desde /etc: {exc}")
            self._status("Error al cargar configuración desde /etc.", 6000)
            return
        self.app_state.entries = [SshfsEntry.from_dict(e) for e in entries]
        self.app_state.master_options.timeout = timeout
        self.app_state.master_options.ghost = ghost
        self._apply_master_options()
        self._refresh_entries_table()
        self._mark_dirty(False)
        message = "Configuración cargada desde /etc." if initial else "Configuración actualizada desde /etc."
        self._append_output(message)
        self._status(message, 6000)
        try:
            self._save_state(silent=True)
        except Exception:
            pass

    def _save_state(self, silent: bool = False) -> None:
        self._remember_ui_state()
        try:
            save_state(self.app_state.to_dict())
        except Exception as exc:
            if silent:
                raise
            self._show_error(f"No se pudo guardar el estado: {exc}")
            return
        if not silent:
            self._append_output(f"Estado guardado en {APP_CONFIG_FILE}")

    def _service_action(self, action: str) -> None:
        titles = {
            "start": "Iniciar servicio",
            "stop": "Detener servicio",
            "restart": "Reiniciar servicio",
        }
        success_texts = {
            "start": "El servicio autofs se inició correctamente.",
            "stop": "El servicio autofs se detuvo correctamente.",
            "restart": "El servicio autofs se reinició correctamente.",
        }
        title = titles.get(action, "Acción del servicio")
        self._set_service_buttons_enabled(False)
        try:
            rc, out, err = self.usecases.service(action)
        except Exception as exc:
            self._show_error(f"No se pudo ejecutar la acción '{action}': {exc}")
            return
        finally:
            self._set_service_buttons_enabled(True)

        if rc == 0:
            message = success_texts.get(action, "Acción completada.")
            self._append_output(message, level="success")
            QMessageBox.information(self, title, message)
        else:
            detail = self._short_text(err or out or "Sin detalles disponibles.")
            message = f"No se pudo completar la acción '{title.lower()}' (código {rc})."
            self._append_output(f"{message} Detalle: {detail}", level="warning")
            QMessageBox.warning(self, title, f"{message}\n\nDetalle:\n{detail}")

        self._check_service_status()

    # ---------------------------------------------------------------- feedback helpers
    def _mark_dirty(self, dirty: bool, reason: Optional[str] = None) -> None:
        self._dirty = dirty
        title = "AutoFS GUI"
        if dirty:
            title += " *"
            self.dirty_label.setText("Cambios sin guardar")
            self.dirty_label.setStyleSheet("color: #d9534f;")
        else:
            self.dirty_label.setText("Sin cambios")
            self.dirty_label.setStyleSheet("")
        self.setWindowTitle(title)
        if dirty and reason:
            self._schedule_apply(reason)

    def _scroll_logs_to_end(self) -> None:
        if self.output_text:
            sb = self.output_text.verticalScrollBar()
            if sb:
                sb.setValue(sb.maximum())

    def _toggle_logs(self, checked: bool) -> None:
        self.logs_box.setVisible(checked)
        self.btn_toggle_logs.setText("Ocultar registros" if checked else "Mostrar registros")

    def _copy_entry_detail(self) -> None:
        data = self._current_entry_json()
        if not data:
            self._status("No hay detalle para copiar.", 4000)
            return
        text = json.dumps(data, indent=2, ensure_ascii=False)
        QApplication.clipboard().setText(text)
        self._status("Detalle copiado al portapapeles.", 4000)

    def _copy_logs(self) -> None:
        text = self.output_text.toPlainText().strip()
        if not text:
            self._status("No hay registros para copiar.", 4000)
            return
        QApplication.clipboard().setText(text)
        self._status("Registros copiados al portapapeles.", 4000)

    def _schedule_apply(self, reason: str) -> None:
        if self._is_applying:
            return
        self._pending_apply_reason = reason
        if self._apply_timer is None:
            self._apply_timer = QTimer(self)
            self._apply_timer.setSingleShot(True)
            self._apply_timer.timeout.connect(self._apply_changes)
        self._apply_timer.start(400)

    def _apply_changes(self) -> None:
        if self._apply_timer:
            self._apply_timer.stop()
        reason = self._pending_apply_reason or "Cambios aplicados."
        self._pending_apply_reason = None
        if self._is_applying:
            return
        self._is_applying = True
        try:
            self._remember_ui_state()
            try:
                self._save_state(silent=True)
            except Exception as exc:
                self._show_error(f"No se pudo guardar el estado local: {exc}")
                return

            if any(entry.allow_other for entry in self.app_state.entries):
                try:
                    self.usecases.enable_user_allow_other(self.usecases.paths.FUSE_CONF)
                    self._append_output("Opción user_allow_other habilitada en fuse.conf.", level="info")
                except PermissionError as exc:
                    self._append_output(f"No se pudo habilitar user_allow_other automáticamente: {exc}", level="warning")
                except Exception as exc:
                    self._append_output(f"Error actualizando fuse.conf: {exc}", level="warning")

            try:
                master_body, map_body = self.usecases.build_files(
                    self._entries_dicts(),
                    self.app_state.master_options.timeout,
                    self.app_state.master_options.ghost,
                )
                result = self.usecases.write_config(master_body, map_body, as_root=is_root())
            except Exception as exc:
                self._show_error(f"No se pudo escribir la configuración: {exc}")
                return

            message = result.get("message", "Operación completada.")
            temporary = result.get("temporary")
            level = "warning" if temporary else "success"
            self._append_output(message, level=level)
            if temporary:
                self._status("Configuración guardada temporalmente. Sigue las instrucciones mostradas.", 8000)
            else:
                self._status(f"{reason} Configuración aplicada.", 6000)
                if self._restart_service_silent():
                    self._verify_mounts()
            self._mark_dirty(False)
        finally:
            self._is_applying = False

    def _restart_service_silent(self) -> bool:
        try:
            rc, out, err = self.usecases.service("restart")
        except Exception as exc:
            self._append_output(f"No se pudo reiniciar autofs: {exc}", level="warning")
            self._status("No se pudo reiniciar autofs.", 6000)
            return False

        if rc == 0:
            self._append_output("Servicio autofs reiniciado correctamente.", level="success")
            self._status("Servicio autofs reiniciado.", 4000)
            self._check_service_status()
            return True
        else:
            detail = self._short_text(err or out or "Sin detalles disponibles.")
            self._append_output(f"No se pudo reiniciar autofs (código {rc}). Detalle: {detail}", level="warning")
            self._status("No se pudo reiniciar autofs.", 6000)
            self._check_service_status()
            return False

    def _verify_mounts(self) -> None:
        if not self.app_state.entries:
            return
        for entry in self.app_state.entries:
            path = entry.mount_point
            path_q = shlex_quote(path)
            ls_cmd = f"ls -la {path_q}"
            try:
                rc, out, err = self.usecases.test_ls(path)
            except Exception as exc:
                self._append_output(f"Verificación fallida para {path}. Comando: {ls_cmd}. Detalle: {exc}", level="warning")
                self._status(f"Montaje no verificado en {path}. Revisa el registro.", 8000)
                continue
            if rc == 0:
                listing = self._short_text(out or "Contenido listado correctamente.", limit=400)
                self._append_output(f"Montaje verificado: {ls_cmd}\n{listing}", level="success")
            else:
                detail = self._short_text(err or out or "Sin detalles disponibles.")
                self._append_output(
                    f"El montaje no respondió correctamente. Comando: {ls_cmd}. Código: {rc}. Detalle: {detail}",
                    level="warning",
                )
                self._status(f"Montaje no verificado en {path}. Revisa el registro.", 8000)
                try:
                    t_rc, t_out, t_err = self.usecases.trigger_mount(path)
                    detail_trigger = self._short_text(t_out or t_err or "", limit=400)
                    level = "info" if t_rc == 0 else "warning"
                    self._append_output(
                        f"Intento adicional con sudo (ls) para {path} retornó código {t_rc}. Detalle: {detail_trigger}",
                        level=level,
                    )
                except Exception as exc:
                    self._append_output(f"Fallo al intentar montar {path} con sudo: {exc}", level="warning")
            mount_cmd = f"mountpoint {path_q}"
            try:
                m_rc, m_out, m_err = self.usecases.check_mount(path)
            except Exception as exc:
                self._append_output(f"No se pudo comprobar el montaje. Comando: {mount_cmd}. Detalle: {exc}", level="warning")
                self._status(f"No se pudo comprobar el montaje en {path}.", 8000)
                continue
            if m_rc == 0:
                detail = self._short_text(m_out or "La ruta es un punto de montaje activo.")
                self._append_output(f"Montaje activo: {mount_cmd}\n{detail}", level="success")
            else:
                detail = self._short_text(m_err or m_out or "Sin detalles disponibles.")
                self._append_output(
                    f"El punto de montaje no aparece como montado. Comando: {mount_cmd}. Código: {m_rc}. Detalle: {detail}",
                    level="warning",
                )
                self._status(f"Montaje no detectado en {path}. Revisa el registro.", 8000)
                try:
                    l_rc, l_out, l_err = self.usecases.collect_autofs_log()
                except Exception as exc:
                    self._append_output(f"No se pudieron obtener logs de autofs: {exc}", level="warning")
                else:
                    if l_rc == 0:
                        snippet = self._short_text(l_out or "(sin salida)", limit=1200)
                        self._append_output("Fragmento del journal de autofs:\n" + snippet, level="info")
                    else:
                        self._append_output(
                            f"No se pudo leer el journal de autofs (código {l_rc}). Detalle: {l_err or l_out}",
                            level="warning",
                        )

    def _status(self, message: str, timeout: int = 5000) -> None:
        self.statusBar().showMessage(message, timeout)

    def _set_output(self, text: str) -> None:
        self.output_text.setPlainText(text.strip() if text else "")
        self._scroll_logs_to_end()

    def _append_output(self, text: str, level: str = "info") -> None:
        if not text:
            return
        timestamp = datetime.now().strftime("%H:%M:%S")
        level_label = {
            "info": "INFO",
            "success": "ÉXITO",
            "warning": "AVISO",
            "error": "ERROR",
        }.get(level, "INFO")
        entry = f"[{timestamp}] {level_label}: {text.strip()}"
        current = self.output_text.toPlainText()
        if current:
            self.output_text.appendPlainText("")
        self.output_text.appendPlainText(entry)
        self._scroll_logs_to_end()

    def _show_error(self, message: str) -> None:
        self._append_output(message, level="error")
        QMessageBox.critical(self, "Error", message)

    # ---------------------------------------------------------------- events
    def closeEvent(self, event) -> None:
        if self._dirty:
            confirm = QMessageBox.question(
                self,
                "Cerrar aplicación",
                "Hay cambios sin guardar en el estado local. ¿Deseas salir igualmente?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if confirm != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
        self._remember_ui_state()
        try:
            save_state(self.app_state.to_dict())
        except Exception:
            pass
        if hasattr(self, "status_timer"):
            self.status_timer.stop()
        super().closeEvent(event)


class EntryDialog(QDialog):
    def __init__(self, parent: Optional[QWidget], entry: Optional[SshfsEntry] = None):
        super().__init__(parent)
        self.setWindowTitle("Agregar entrada" if entry is None else "Editar entrada")
        self._result: Optional[SshfsEntry] = None

        layout = QVBoxLayout(self)
        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)

        self.mount_edit = QLineEdit(entry.mount_point if entry else "")
        self.mount_edit.setPlaceholderText("Ej.: /mnt/proyecto")
        mount_container = QWidget()
        mount_layout = QHBoxLayout(mount_container)
        mount_layout.setContentsMargins(0, 0, 0, 0)
        mount_layout.setSpacing(6)
        mount_layout.addWidget(self.mount_edit)
        self.mount_browse = QPushButton("Elegir…")
        self.mount_browse.setToolTip("Selecciona una carpeta local como punto de montaje.")
        self.mount_browse.clicked.connect(self._select_mount_point)
        mount_layout.addWidget(self.mount_browse)
        form.addRow("Punto de montaje", mount_container)

        self.host_candidates: List[HostCandidate] = []
        self.host_combo = QComboBox()
        self.host_combo.setEditable(True)
        self.host_combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.host_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        self.host_combo.lineEdit().setPlaceholderText("Ej.: servidor.local")
        if entry and entry.host:
            self.host_combo.setEditText(entry.host)
        host_container = QWidget()
        host_layout = QHBoxLayout(host_container)
        host_layout.setContentsMargins(0, 0, 0, 0)
        host_layout.setSpacing(6)
        host_layout.addWidget(self.host_combo, stretch=1)
        self.btn_hosts_refresh = QPushButton("Buscar")
        self.btn_hosts_refresh.setToolTip("Buscar hosts disponibles en la red (mDNS, Tailscale, etc.).")
        self.btn_hosts_refresh.clicked.connect(lambda: self._load_hosts_async(force=True))
        host_layout.addWidget(self.btn_hosts_refresh)
        form.addRow("Host", host_container)

        self.remote_edit = QLineEdit(entry.remote_path if entry else "")
        form.addRow("Ruta remota", self.remote_edit)

        self.user_edit = QLineEdit(entry.user if entry else "")
        form.addRow("Usuario", self.user_edit)

        self.fstype_edit = QLineEdit(entry.fstype if entry else "fuse.sshfs")
        form.addRow("FSType", self.fstype_edit)

        identity_default = entry.identity_file if entry and entry.identity_file else self._default_identity_path()
        self.identity_edit = QLineEdit(identity_default)
        identity_container = QWidget()
        identity_layout = QHBoxLayout(identity_container)
        identity_layout.setContentsMargins(0, 0, 0, 0)
        identity_layout.setSpacing(6)
        identity_layout.addWidget(self.identity_edit, stretch=1)
        self.identity_browse = QPushButton("Elegir…")
        self.identity_browse.setToolTip("Selecciona el archivo de identidad SSH a utilizar.")
        self.identity_browse.clicked.connect(self._select_identity_file)
        identity_layout.addWidget(self.identity_browse)
        form.addRow("Identity file", identity_container)

        self.allow_other_chk = QCheckBox("allow_other")
        self.allow_other_chk.setChecked(entry.allow_other if entry else True)
        form.addRow("Opciones generales", self.allow_other_chk)

        self.uid_edit = QLineEdit(entry.uid if entry else "1000")
        form.addRow("UID", self.uid_edit)

        self.gid_edit = QLineEdit(entry.gid if entry else "1000")
        form.addRow("GID", self.gid_edit)

        self.umask_edit = QLineEdit(entry.umask if entry else "022")
        form.addRow("Umask", self.umask_edit)

        self.sai_spin = QSpinBox()
        self.sai_spin.setRange(0, 3600)
        self.sai_spin.setValue(entry.server_alive_interval if entry else 15)
        form.addRow("ServerAliveInterval", self.sai_spin)

        self.sac_spin = QSpinBox()
        self.sac_spin.setRange(1, 60)
        self.sac_spin.setValue(entry.server_alive_count if entry else 3)
        form.addRow("ServerAliveCountMax", self.sac_spin)

        self.reconnect_chk = QCheckBox("reconnect")
        self.reconnect_chk.setChecked(entry.reconnect if entry else True)
        self.delay_connect_chk = QCheckBox("delay_connect")
        self.delay_connect_chk.setChecked(entry.delay_connect if entry else True)

        reconnect_box = QHBoxLayout()
        reconnect_box.addWidget(self.reconnect_chk)
        reconnect_box.addWidget(self.delay_connect_chk)
        reconnect_box.addStretch()
        form.addRow("Reconexión", reconnect_box)

        self.extra_edit = QLineEdit(entry.extra_options if entry else "")
        form.addRow("Opciones extra", self.extra_edit)

        layout.addLayout(form)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.resize(460, 0)
        self._host_loader: Optional[threading.Thread] = None
        self._load_hosts_async(initial=True, force=True)

    def _select_mount_point(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Seleccionar punto de montaje")
        if path:
            self.mount_edit.setText(path)

    def _current_host_text(self) -> str:
        text = self.host_combo.currentText().strip()
        idx = self.host_combo.currentIndex()
        if idx >= 0:
            data = self.host_combo.itemData(idx)
            if isinstance(data, str) and data.strip():
                text = data.strip()
        return text

    def _load_hosts_async(self, initial: bool = False, force: bool = False) -> None:
        if hasattr(self, "_host_loader") and self._host_loader and self._host_loader.is_alive():
            return
        current = self._current_host_text()
        if current:
            self.host_combo.setEditText(current)
        self.btn_hosts_refresh.setEnabled(False)
        if initial:
            self.host_combo.lineEdit().setPlaceholderText("Buscando hosts…")

        try:
            cached_hosts = discover_hosts(force=False)
        except Exception:
            cached_hosts = []
        if cached_hosts:
            self._apply_host_candidates(cached_hosts, "")

        def worker():
            try:
                hosts = discover_hosts(force=force)
                error = ""
            except Exception as exc:
                hosts = []
                error = str(exc)
            QTimer.singleShot(0, lambda: self._apply_host_candidates(hosts, error))

        thread = threading.Thread(target=worker, daemon=True)
        self._host_loader = thread
        thread.start()

    def _apply_host_candidates(self, hosts: List[HostCandidate], error: str) -> None:
        self.host_candidates = hosts
        current = self._current_host_text()
        self.host_combo.blockSignals(True)
        self.host_combo.clear()
        seen = set()
        for cand in hosts:
            key = cand.name.lower()
            if key in seen:
                continue
            seen.add(key)
            label = cand.name
            if cand.address:
                label += f" ({cand.address})"
            label += f" [{cand.source}]"
            self.host_combo.addItem(label, cand.name)

        if current:
            self.host_combo.setEditText(current)
        elif hosts:
            self.host_combo.setCurrentIndex(0)
            self.host_combo.setEditText(hosts[0].name)
        else:
            self.host_combo.setEditText(current)
        self.host_combo.blockSignals(False)
        self.host_combo.lineEdit().setPlaceholderText("Ej.: servidor.local")
        self.btn_hosts_refresh.setEnabled(True)

        parent = self.parent()
        if error:
            if parent and hasattr(parent, "_append_output"):
                parent._append_output(f"No se pudo descubrir hosts: {error}", level="warning")
        elif hosts and parent and hasattr(parent, "_append_output"):
            preview = ", ".join(c.name for c in hosts[:8])
            if len(hosts) > 8:
                preview += ", …"
            parent._append_output(f"Hosts detectados ({len(hosts)}): {preview}", level="info")

    def _default_identity_path(self) -> str:
        root_key = "/root/.ssh/id_ed25519"
        if os.path.exists(root_key):
            return root_key
        user_key = os.path.expanduser("~/.ssh/id_ed25519")
        if os.path.exists(user_key):
            return user_key
        return ""

    def _select_identity_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Seleccionar archivo de identidad", os.path.expanduser("~"))
        if path:
            self.identity_edit.setText(path)

    def accept(self) -> None:
        data = {
            "mount_point": self.mount_edit.text().strip(),
            "host": self._current_host_text(),
            "remote_path": self.remote_edit.text().strip(),
            "user": self.user_edit.text().strip(),
            "fstype": self.fstype_edit.text().strip() or "fuse.sshfs",
            "identity_file": self.identity_edit.text().strip(),
            "allow_other": self.allow_other_chk.isChecked(),
            "uid": self.uid_edit.text().strip() or "1000",
            "gid": self.gid_edit.text().strip() or "1000",
            "umask": self.umask_edit.text().strip() or "022",
            "server_alive_interval": int(self.sai_spin.value()),
            "server_alive_count": int(self.sac_spin.value()),
            "reconnect": self.reconnect_chk.isChecked(),
            "delay_connect": self.delay_connect_chk.isChecked(),
            "extra_options": self.extra_edit.text().strip(),
        }
        try:
            validate_entry(data)
        except ValueError as exc:
            QMessageBox.warning(self, "Entrada inválida", str(exc))
            return

        self._result = SshfsEntry(**data)
        super().accept()

    def get_entry(self) -> Optional[SshfsEntry]:
        return self._result
